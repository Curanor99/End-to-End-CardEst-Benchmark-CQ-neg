from itertools import combinations
from pathlib import Path

import sqlglot
from sqlglot import exp

QUERY_FILE_PATH = Path("scripts/py/util/test.sql")


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

    # Collect equalities from every SELECT, including nested SELECTs.
    for select in get_scopes(tree):
        for left, right in extract_equalities(select):
            union(left, right)

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


def tables_in_select(select):
    return [
        table
        for table in select.find_all(exp.Table)
        if enclosing_select(table) is select
    ]


def get_scopes(tree):
    return list(tree.find_all(exp.Select))


def extract_equalities(select):
    equalities = []

    for node in select.find_all(exp.EQ):
        if enclosing_select(node) is not select:
            continue

        left = node.this
        right = node.expression

        if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
            continue

        if not left.table or not right.table:
            continue

        if left.table == right.table:
            continue

        equalities.append(((left.table, left.name), (right.table, right.name)))

    return equalities


def extract_negated_tables(tree):
    negated_tables = set()

    for exists in tree.find_all(exp.Exists):
        if not isinstance(exists.parent, exp.Not):
            continue

        subquery = exists.this

        if isinstance(subquery, exp.Subquery):
            subquery = subquery.this

        if isinstance(subquery, exp.Select):
            for table in tables_in_select(subquery):
                negated_tables.add(table)

    return negated_tables


def extract_hypergraph(tree):
    atoms = []
    negated_tables = extract_negated_tables(tree)

    # Build equivalence classes only once.
    variable_mapping = build_variable_mapping(tree)

    for select in get_scopes(tree):
        tables = tables_in_select(select)

        # Only consider equalities belonging to this SELECT.
        equalities = extract_equalities(select)

        for table in tables:
            alias = table.alias_or_name
            columns = set()

            for left, right in equalities:
                for column in (left, right):
                    if column[0] == alias:
                        columns.add(column)

            # Resolve variables using the shared mapping.
            atom_variables = {
                variable_mapping[column]
                for column in columns
                if column in variable_mapping
            }

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


#### Beta-acyclicity

def is_nest_point(vertex, edges):
    incident = [
        edge
        for edge in edges
        if vertex in edge
    ]

    for i, first in enumerate(incident):
        for second in incident[i + 1:]:
            if not (first <= second or second <= first):
                return False

    return True


def reverse_elimination_ordering(edges):
    edges = set(edges)
    vertices = set().union(*edges) if edges else set()
    ordering = []

    while vertices:
        removable = sorted(
            vertex
            for vertex in vertices
            if is_nest_point(vertex, edges)
        )

        if not removable:
            return None

        vertex = removable[0]

        ordering.append(vertex)
        vertices.remove(vertex)

        edges = {
            frozenset(edge - {vertex})
            for edge in edges
        }

    return ordering


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


def is_nest_set(possible_nest_set, edges):
    incident = [
        edge - possible_nest_set
        for edge in edges
        if edge & possible_nest_set
    ]

    for i, first in enumerate(incident):
        for second in incident[i + 1:]:
            if not (first <= second or second <= first):
                return False

    return True


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
    edges = set(edges)
    vertices = set().union(*edges) if edges else set()

    possible_neos = get_all_possible_neos([], vertices)

    neos = []

    for possible_neo in possible_neos:
        if is_neo(possible_neo, edges):
            neos.append(possible_neo)

    return get_smallest_k_neo(neos)


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

        print(f"Query with query id {query_id} beta-acyclic:", neo[0] == 1)
        print(f"Query with query id {query_id} has nest-set width:", neo[0])
        print(f"Query with query id {query_id} signed-acyclic:", is_signed_acyclic(positive_edges, negated_edges))

if __name__ == '__main__':
    main()