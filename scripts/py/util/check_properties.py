from functools import lru_cache
from itertools import combinations
from pathlib import Path

import sqlglot
from sqlglot import exp

QUERY_FILE_PATH = Path("workloads/cardest_workload_and_protocol/cardest_negate_existing_atoms/not_exists.sql")
OUTPUT_FILE = Path("workloads/cardest_workload_and_protocol/cardest_negate_existing_atoms/structural_properties.csv")


def build_variable_mapping(tree):
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

    scopes = get_scopes(tree)
    tables_by_scope = {
        id(select): tables_in_select(select)
        for select in scopes
    }

    # Give every referenced column a scope-qualified identity. This keeps
    # reused aliases in nested SELECTs distinct while resolving correlations.
    column_keys = {}
    for select in scopes:
        for column in select.find_all(exp.Column):
            if enclosing_select(column) is not select:
                continue
            column_keys[id(column)] = resolve_column(column, select, tables_by_scope)
            find(column_keys[id(column)])

    for select in scopes:
        for node in select.find_all(exp.EQ):
            if enclosing_select(node) is not select:
                continue
            left, right = node.this, node.expression
            if isinstance(left, exp.Column) and isinstance(right, exp.Column):
                union(column_keys[id(left)], column_keys[id(right)])

    # Assign variable names.
    variables = {}

    def get_variable(column):
        representative = find(column)

        if representative not in variables:
            variables[representative] = f"X{len(variables) + 1}"

        return variables[representative]

    return {
        column: get_variable(column)
        for column in parent
    }


def read_queries():
    queries = {}
    with open(QUERY_FILE_PATH, "r") as query_file:
        for line in query_file:
            query_id, query = line.strip("\n").split("||")

            queries[query_id] = query

    return queries


### Extract hypergraph infos

def enclosing_select(node):
    parent = node.parent

    while parent is not None:
        if isinstance(parent, exp.Select):
            return parent
        parent = parent.parent

    return None


def normalized_name(name):
    return name.casefold()


def tables_in_select(select):
    return [
        table
        for table in select.find_all(exp.Table)
        if enclosing_select(table) is select
    ]


def get_scopes(tree):
    return list(tree.find_all(exp.Select))


def resolve_column(column, select, tables_by_scope):
    qualifier = normalized_name(column.table) if column.table else None
    current_scope = select

    while current_scope is not None:
        tables = tables_by_scope[id(current_scope)]
        if qualifier:
            matches = [
                table for table in tables
                if normalized_name(table.alias_or_name) == qualifier
            ]
            if len(matches) > 1:
                raise ValueError(
                    f"Ambiguous table alias {column.table!r} in SELECT scope"
                )
            if matches:
                table = matches[0]
                return (
                    id(current_scope),
                    normalized_name(table.alias_or_name),
                    normalized_name(column.name),
                )
        elif len(tables) == 1:
            table = tables[0]
            return (
                id(current_scope),
                normalized_name(table.alias_or_name),
                normalized_name(column.name),
            )
        elif len(tables) > 1:
            raise ValueError(
                f"Cannot resolve unqualified column {column.name!r} "
                "in a SELECT with multiple tables"
            )

        current_scope = enclosing_select(current_scope)

    qualifier_text = f"{column.table}." if column.table else ""
    raise ValueError(f"Cannot resolve column {qualifier_text}{column.name}")


def extract_negated_tables(tree):
    negated_tables = set()

    for exists in tree.find_all(exp.Exists):
        if not isinstance(exists.parent, exp.Not):
            continue

        subquery = exists.this

        if isinstance(subquery, exp.Subquery):
            subquery = subquery.this

        if not isinstance(subquery, exp.Select):
            continue

        tables = tables_in_select(subquery)
        nested_selects = [
            select for select in subquery.find_all(exp.Select)
            if select is not subquery
        ]
        if len(tables) != 1 or nested_selects:
            raise ValueError(
                "Only single-table NOT EXISTS subqueries without nested "
                "subqueries can be represented as one negated CQ atom"
            )
        negated_tables.add(tables[0])

    return negated_tables


def extract_hypergraph(tree):
    atoms = []
    negated_tables = extract_negated_tables(tree)

    # Build equivalence classes only once.
    variable_mapping = build_variable_mapping(tree)

    for select in get_scopes(tree):
        for table in tables_in_select(select):
            alias = table.alias_or_name
            table_key = (id(select), normalized_name(table.alias_or_name))
            atom_variables = {
                variable
                for column, variable in variable_mapping.items()
                if column[:2] == table_key
            }

            # Unreferenced schema columns are private degree-one vertices,
            # which do not change alpha/beta acyclicity or nest-set width.
            # Keep one placeholder when an atom has no referenced columns.
            if not atom_variables:
                atom_variables.add(f"private_{id(table)}")

            atoms.append({
                "relation": table.name,
                "alias": alias,
                "negated": table in negated_tables,
                "variables": atom_variables
            })

    return atoms


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


def is_neo(possible_neo, edges):
    current_edges = edges.copy()

    for possible_nest_set in possible_neo:
        if not is_nest_set(possible_nest_set, current_edges):
            return False

        current_edges = {
            frozenset(edge - possible_nest_set)
            for edge in current_edges
            if edge - possible_nest_set
        }

    return not current_edges


def get_smallest_k_neo(neos):
    if not neos:
        return None

    k_neos = [(len(max(neo, key=len)), neo) for neo in neos]

    smallest_k_neo = None

    for k, neo in k_neos:
        if smallest_k_neo is None or k < smallest_k_neo[0]:
            smallest_k_neo = (k, neo)

    return smallest_k_neo


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
    queries = read_queries()
    with open(OUTPUT_FILE, "w+") as output_file:
        output_file.write("query_id,nest-set width,beta-acyclic,signed-acyclic\n")
        for query_id in queries:
            tree = sqlglot.parse_one(queries[query_id], read="tsql")

            atoms = extract_hypergraph(tree)
            positive_atoms, negated_atoms = [], []
            for atom in atoms:
                if atom["negated"]:
                    negated_atoms.append(atom)
                else:
                    positive_atoms.append(atom)
            edges = atoms_to_hypergraph(atoms)
            positive_edges, negated_edges = atoms_to_hypergraph(positive_atoms), atoms_to_hypergraph(negated_atoms)

            neo = nest_set_elimination_ordering(edges)

            nest_set_width = neo[0]
            beta_acyclic = nest_set_width == 1
            signed_acyclic = is_signed_acyclic(positive_edges, negated_edges)

            output_file.write(f"{query_id},{nest_set_width},{beta_acyclic},{signed_acyclic}\n")

            print(f"Query with query id {query_id} beta-acyclic:", beta_acyclic)
            print(f"Query with query id {query_id} has nest-set width:", nest_set_width)
            print(f"Query with query id {query_id} signed-acyclic:", signed_acyclic)



if __name__ == '__main__':
    main()