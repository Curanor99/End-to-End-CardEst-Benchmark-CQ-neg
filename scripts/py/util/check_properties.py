from collections import defaultdict
from functools import lru_cache
from itertools import combinations
from pathlib import Path

import sqlglot
from sqlglot import exp

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SCHEMA_FILE = PROJECT_ROOT / "scripts" / "sql" / "stats.sql"
QUERY_FILE_PATH = PROJECT_ROOT / "workloads" / "cardest_workload_and_protocol" / "cardest_negate_existing_atoms" / "not_exists.sql"
OUTPUT_FILE = PROJECT_ROOT / "workloads" / "cardest_workload_and_protocol" / "cardest_negate_existing_atoms" / "structural_properties.csv"


### Schema Loading

def load_schema(path):
    schema = {}
    for stmt in sqlglot.parse(Path(path).read_text(), read="tsql"):
        if isinstance(stmt, exp.Create) and isinstance(stmt.this, exp.Schema):
            table = normalized_name(stmt.this.this.name)
            schema[table] = {
                normalized_name(c.name)
                for c in stmt.this.expressions
                if isinstance(c, exp.ColumnDef)
            }
    return schema


def cte_schemas(tree):
    return {
        normalized_name(cte.alias): {
            normalized_name(p.alias_or_name) for p in cte.this.selects
        }
        for cte in tree.find_all(exp.CTE)
    }


def is_derived_table(node):
    return isinstance(node, exp.Subquery) and isinstance(node.parent, (exp.From, exp.Join))


def enclosing_select(node):
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Select):
            return parent
        # CTE bodies and derived tables are separate units
        if isinstance(parent, exp.CTE) or is_derived_table(parent):
            return None
        parent = parent.parent
    return None


def tables_in_select(select):
    """All FROM/JOIN sources of this select: base tables, CTE refs, derived tables."""
    return [
        n for n in select.find_all(exp.Table, exp.Subquery)
        if (isinstance(n, exp.Table) or is_derived_table(n))
           and enclosing_select(n) is select
    ]


def source_columns(src, schema):
    if isinstance(src, exp.Subquery):
        # for INTERSECT/UNION, .selects gives the left-most branch's projections
        return {normalized_name(p.alias_or_name) for p in src.selects}
    return schema.get(normalized_name(src.name), set())


def source_label(src):
    return f"derived:{src.alias}" if isinstance(src, exp.Subquery) else src.name


def unit_label(root):
    parts, node = [], root.parent
    while node is not None:
        if isinstance(node, exp.CTE):
            parts.append(f"cte:{node.alias}")
            break
        if is_derived_table(node):
            parts.append(f"derived:{node.alias}")
        node = node.parent
    return " > ".join(reversed(parts)) or "main"


def read_queries():
    queries = {}
    with open(QUERY_FILE_PATH, "r") as query_file:
        for line in query_file:
            query_id, query = line.strip("\n").split("||")

            queries[query_id] = query

    return queries


def get_units(tree):
    return [s for s in tree.find_all(exp.Select) if enclosing_select(s) is None]


def unit_root_of(select):
    while (outer := enclosing_select(select)) is not None:
        select = outer
    return select


def scopes_of_unit(root):
    return [s for s in root.find_all(exp.Select) if unit_root_of(s) is root]


### Extract hypergraph infos

def resolve_column(column, select, tables_by_scope, schema):
    qualifier = normalized_name(column.table) if column.table else None
    name = normalized_name(column.name)
    current = select

    while current is not None:
        tables = tables_by_scope[id(current)]
        if qualifier:
            matches = [t for t in tables
                       if normalized_name(t.alias_or_name) == qualifier]
        else:
            matches = [t for t in tables if name in source_columns(t, schema)]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous column {column.sql()}")
        if matches:
            return (id(current), normalized_name(matches[0].alias_or_name), name)
        current = enclosing_select(current)

    scope_info = [
        f"{t.alias_or_name}({source_label(t)}, "
        f"{'in schema' if source_columns(t, schema) else 'NOT in schema'})"
        for t in tables_by_scope[id(select)]
    ]
    raise ValueError(
        f"Cannot resolve {column.sql()}; tables in innermost scope: {scope_info}"
    )


def build_variable_mapping(scopes, schema):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        x, y = find(x), find(y)
        if x != y:
            parent[y] = x

    tables_by_scope = {id(s): tables_in_select(s) for s in scopes}

    column_keys, records = {}, []
    for select in scopes:
        for column in select.find_all(exp.Column):
            if enclosing_select(column) is not select:
                continue
            key = resolve_column(column, select, tables_by_scope, schema)
            column_keys[id(column)] = key
            records.append((select, key))
            find(key)

    for select in scopes:
        for node in select.find_all(exp.EQ):
            if enclosing_select(node) is not select:
                continue
            l, r = node.this, node.expression
            if isinstance(l, exp.Column) and isinstance(r, exp.Column):
                union(column_keys[id(l)], column_keys[id(r)])

    variables = {}
    mapping = {}
    for key in parent:
        rep = find(key)
        variables.setdefault(rep, f"X{len(variables) + 1}")
        mapping[key] = variables[rep]
    return mapping, records


def normalized_name(name):
    return name.casefold()


def get_scopes(tree):
    return list(tree.find_all(exp.Select))


def negated_subqueries(scopes):
    result = []
    for select in scopes:
        for ex in select.find_all(exp.Exists):
            if enclosing_select(ex) is not select or not isinstance(ex.parent, exp.Not):
                continue
            sub = ex.this.this if isinstance(ex.this, exp.Subquery) else ex.this
            if not isinstance(sub, exp.Select):
                raise ValueError("NOT EXISTS over a set operation is not supported")
            result.append(sub)
    return result


def extract_hypergraph(root, schema):
    scopes = scopes_of_unit(root)
    neg_roots = negated_subqueries(scopes)
    neg_ids = {id(s) for s in neg_roots}

    def group_of(select):                 # id of enclosing NOT EXISTS, or None
        while select is not None:
            if id(select) in neg_ids:
                return id(select)
            select = enclosing_select(select)
        return None

    group = {id(s): group_of(s) for s in scopes}
    for r in neg_roots:
        if group_of(enclosing_select(r)) is not None:
            raise ValueError("Nested NOT EXISTS is not supported")

    mapping, records = build_variable_mapping(scopes, schema)

    # free variables of a negated block = variables of columns it references
    # that were resolved outside of it (equality- or inequality-correlated)
    free = defaultdict(set)
    for scope, key in records:
        g = group[id(scope)]
        if g is not None and group[key[0]] != g:
            free[g].add(mapping[key])

    atoms = []
    for select in scopes:
        if group[id(select)] is not None:
            continue
        for table in tables_in_select(select):
            table_key = (id(select), normalized_name(table.alias_or_name))
            variables = {v for k, v in mapping.items() if k[:2] == table_key}
            if not variables:
                variables = {f"private_{id(table)}"}
            atoms.append({"relation": source_label(table), "alias": table.alias_or_name,
                          "negated": False, "variables": variables})

    for r in neg_roots:
        rels = [source_label(t) for s in scopes if group[id(s)] == id(r)
                for t in tables_in_select(s)]
        atoms.append({"relation": "NOT EXISTS(" + "+".join(rels) + ")",
                      "alias": f"neg_{id(r)}", "negated": True,
                      "variables": set(free[id(r)]) or {f"private_{id(r)}"}})
    return atoms


def analyze_unit(root, schema):
    atoms = extract_hypergraph(root, schema)
    pos = atoms_to_hypergraph([a for a in atoms if not a["negated"]])
    neg = atoms_to_hypergraph([a for a in atoms if a["negated"]])
    width, _ = nest_set_elimination_ordering(atoms_to_hypergraph(atoms))
    return {"width": width, "beta": width <= 1,
            "signed": is_signed_acyclic(pos, neg)}


def atoms_to_hypergraph(atoms):
    return {
        frozenset(atom["variables"])
        for atom in atoms
    }


### Nest-set width
def get_possible_nest_sets_of_size(vertices, size):
    possible_nest_sets = []

    for combination in combinations(vertices, size):
        possible_nest_sets.append(frozenset(combination))

    return possible_nest_sets


def get_all_possible_neos(possible_neo, vertices):
    if len(vertices) == 0:
        return [possible_neo]

    possible_neos = []

    for size in range(1, len(vertices) + 1):
        vertex_combinations = get_possible_nest_sets_of_size(vertices, size)

        for vertex_combination in vertex_combinations:
            current_possible_neo = possible_neo.copy()
            current_possible_neo.append(vertex_combination)
            possible_neos += get_all_possible_neos(current_possible_neo, vertices.difference(vertex_combination))

    return possible_neos


def nest_set_elimination_ordering(edges):
    edges = frozenset(
        frozenset(edge)
        for edge in edges
        if edge
    )

    if not edges:
        return 0, []

    vertices = set().union(*edges)

    def is_nest_set(nest_set, current_edges):
        incident = [
            edge - nest_set
            for edge in current_edges
            if edge & nest_set
        ]

        for i, first in enumerate(incident):
            for second in incident[i + 1:]:
                if not (first <= second or second <= first):
                    return False

        return True

    def remove_nest_set(nest_set, current_edges):
        return frozenset(
            frozenset(edge - nest_set)
            for edge in current_edges
            if edge - nest_set
        )

    # Try increasing width bounds. The first successful result
    # is therefore an ordering with minimum width.
    for max_width in range(1, len(vertices) + 1):

        @lru_cache(maxsize=None)
        def search(current_edges):
            if not current_edges:
                return ()

            remaining_vertices = sorted(
                set().union(*current_edges)
            )

            # Try smaller nest sets first.
            for size in range(1, min(max_width, len(remaining_vertices)) + 1):
                for combination in combinations(remaining_vertices, size):
                    nest_set = frozenset(combination)

                    if not is_nest_set(nest_set, current_edges):
                        continue

                    next_edges = remove_nest_set(
                        nest_set,
                        current_edges
                    )

                    result = search(next_edges)

                    if result is not None:
                        return (nest_set,) + result

            return None

        ordering = search(edges)

        if ordering is not None:
            return max(len(nest_set) for nest_set in ordering), list(ordering)

    return None


### Signed-acyclicity

def vertex_appearances_in_edges(edges):
    vertex_appearances = {}

    for edge in edges:
        for vertex in edge:
            if vertex not in vertex_appearances:
                vertex_appearances[vertex] = 0

            vertex_appearances[vertex] += 1

    for vertex in vertex_appearances:
        if vertex_appearances[vertex] == 1:
            return vertex

    return None


def find_edge_contained_by_other_edge(edges):
    edges_list = list(edges)
    for contained_index in range(0, len(edges_list)):
        for container_index in range(0, len(edges_list)):
            if contained_index == container_index:
                continue

            if edges_list[contained_index].issubset(edges_list[container_index]):
                return edges_list[contained_index]

    return None


def is_alpha_acyclic(edges):
    current_edges = set(edges)

    while current_edges:
        vertex = vertex_appearances_in_edges(current_edges)

        if vertex is not None:
            current_edges = {
                frozenset(edge - {vertex})
                for edge in current_edges
                if edge - {vertex}
            }
            continue

        edge = find_edge_contained_by_other_edge(current_edges)

        if edge is not None:
            current_edges.remove(edge)
            continue

        return False

    return True


def is_signed_acyclic(positive_edges, negated_edges):
    negated_edges = list(negated_edges)

    for size in range(len(negated_edges) + 1):
        for combination in combinations(negated_edges, size):
            current_edges = positive_edges.union(combination)

            if not is_alpha_acyclic(current_edges):
                return False

    return True


def main():
    base_schema = load_schema(SCHEMA_FILE)
    queries = read_queries()
    totals = defaultdict(int)

    with open(OUTPUT_FILE, "w") as out:
        out.write("query_id,unit,kind,nest-set width,beta-acyclic,signed-acyclic\n")
        for query_id, sql in queries.items():
            results = []
            try:
                for tree in sqlglot.parse(sql, read="tsql"):
                    if tree is None:
                        continue
                    schema = {**base_schema, **cte_schemas(tree)}
                    for root in get_units(tree):
                        res = analyze_unit(root, schema)
                        res["kind"] = unit_label(root)
                        results.append(res)
                        out.write(f"{query_id},{len(results)},{res['kind']},"
                                  f"{res['width']},{res['beta']},{res['signed']}\n")
            except ValueError as e:
                print(f"{query_id}: FAILED: {e}")
                out.write(f"{query_id},ALL,error,,,\n")
                totals["failed"] += 1
                continue

            width = max(r["width"] for r in results)
            beta = all(r["beta"] for r in results)
            signed = all(r["signed"] for r in results)
            out.write(f"{query_id},ALL,summary,{width},{beta},{signed}\n")

            totals["queries"] += 1
            totals["units"] += len(results)
            totals["beta_acyclic"] += beta
            totals["signed_acyclic"] += signed
            print(f"{query_id}: {len(results)} units, width={width}, "
                  f"beta={beta}, signed={signed}")

    print(dict(totals))



if __name__ == '__main__':
    main()