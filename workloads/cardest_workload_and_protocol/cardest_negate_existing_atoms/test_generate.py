from collections import Counter, defaultdict
import csv
import runpy
import sqlite3
import unittest

import generate
import negation_common as common


class GenerateTests(unittest.TestCase):
    def test_sequence_keeps_every_positive_graph_connected(self):
        lines = common.SOURCE.read_text(encoding="utf-8").splitlines()
        bases = common.select_bases(lines)
        orders = defaultdict(list)
        with (generate.ROOT / "manifest.csv").open(newline="", encoding="utf-8") as manifest:
            for row in csv.DictReader(manifest):
                orders[int(row["source_line"])].append(tuple(row["negated_aliases"].split()))
        self.assertEqual(list(orders), [number for number, _, _, _ in bases])
        first_tables = Counter()
        for number, _, sources, conditions in bases:
            order = orders[number][-1]
            self.assertEqual(len(order), len(generate.sequence(sources, conditions)))
            self.assertEqual(orders[number], [order[:i] for i in range(len(order) + 1)])
            tables = {alias: table for table, alias in sources}
            first_tables[tables[order[0]]] += 1
            for count in range(1, len(order) + 1):
                negative = set(order[:count])
                positive = {alias for _, alias in sources} - negative
                edges = [refs for _, refs in conditions if len(refs) == 2]
                self.assertFalse(any(edge <= negative for edge in edges), number)
                reached = {next(iter(positive))}
                while True:
                    expanded = reached | set().union(
                        *(edge for edge in edges if edge <= positive and edge & reached)
                    )
                    if expanded == reached:
                        break
                    reached = expanded
                self.assertEqual(reached, positive, (number, count))
        self.assertEqual(len(first_tables), 8)
        self.assertLessEqual(max(first_tables.values()) - min(
            count for table, count in first_tables.items() if table != "tags"), 2)

    def test_balancer_counts_carried_atoms_at_later_depths(self):
        candidates = {1: [("a", "a", "b")], 2: [("b",)],
                      3: [("a", "c", "d"), ("b", "c", "d")]}
        self.assertEqual(common.balanced_sequences(candidates, lambda _, atom: atom)[3],
                         ("b", "c", "d"))

    def test_base_selector_keeps_every_source_line(self):
        lines = common.SOURCE.read_text(encoding="utf-8").splitlines()
        bases = common.select_bases(lines)
        self.assertEqual([number for number, _, _, _ in bases], list(range(1, len(lines) + 1)))
        self.assertEqual([query for _, query, _, _ in bases],
                         [line.split("||", 1)[1] for line in lines])

    def test_added_manifest_preserves_bases_and_balances_physical_tables(self):
        root = generate.ROOT.parent / "cardest_added_negation"
        lines = common.SOURCE.read_text(encoding="utf-8").splitlines()
        bases = common.select_bases(lines)
        added = runpy.run_path(str(root / "generate.py"))
        eligible = {number: {template[0]: template[1]
                             for template in added["eligible_templates"](sources)}
                    for number, _, sources, _ in bases}
        orders = defaultdict(list)
        first_tables = Counter()
        with (root / "manifest.csv").open(newline="", encoding="utf-8") as manifest:
            for row in csv.DictReader(manifest):
                number = int(row["source_line"])
                depth = int(row["negated_count"])
                order = tuple(row["added_templates"].split())
                positive = {item.split(":")[0] for item in row["positive_relations"].split()}
                tables = eligible[number]
                self.assertEqual(len(order), depth)
                negated = {tables[name] for name in order}
                self.assertEqual(len(negated), depth)
                self.assertTrue(positive.isdisjoint(negated))
                orders[number].append(order)
                if depth == 1:
                    first_tables[tables[order[0]]] += 1
        self.assertEqual(list(orders), [number for number, _, _, _ in bases])
        for number, prefixes in orders.items():
            self.assertGreater(len(prefixes), 1)
            self.assertEqual(len(prefixes) - 1, min(added["MAX_ADDED"],
                                                    len(set(eligible[number].values()))))
            self.assertEqual(prefixes, [prefixes[-1][:i] for i in range(len(prefixes))])
        self.assertEqual(set(first_tables), {template[1] for template in added["TEMPLATES"]})
        self.assertLessEqual(max(first_tables.values()) - min(first_tables.values()), 1)

    def test_connected_sequence_is_maximal_not_greedy(self):
        sources = [(name, name) for name in "abcd"]
        conditions = [
            (f"{a}.id = {b}.id", {a, b})
            for a, b in ("ab", "ac", "ad", "bc", "bd")
        ]
        self.assertEqual(generate.sequence(sources, conditions), ("c", "d"))

    def test_sql_representations_agree_with_nulls_and_duplicates(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript("""
            CREATE TABLE a (id INTEGER, value INTEGER);
            CREATE TABLE b (id INTEGER, value INTEGER);
            CREATE TABLE c (id INTEGER, other INTEGER, enabled INTEGER);
            CREATE TABLE d (id INTEGER);
            INSERT INTO a VALUES (1, 10), (1, 10), (2, NULL), (3, 30), (NULL, 40);
            INSERT INTO b VALUES (1, 10), (1, 10), (2, NULL), (3, 30);
            INSERT INTO c VALUES (1, 10, 1), (1, 10, 1), (3, NULL, 1),
                                 (3, 30, 0), (NULL, 30, 1);
            INSERT INTO d VALUES (2), (NULL);
        """)
        sources = [("a", "a"), ("b", "b"), ("c", "c"), ("d", "d")]
        conditions = [
            ("a.id = b.id", {"a", "b"}),
            ("a.id = c.id", {"a", "c"}),
            ("b.value = c.other", {"b", "c"}),
            ("c.enabled = 1", {"c"}),
            ("a.id = d.id", {"a", "d"}),
        ]
        for negative in ({"c"}, {"d"}, {"c", "d"}):
            counts = {}
            for style in ("not_exists", "not_in", "left_join", "except"):
                sql = generate.build_sql(sources, conditions, negative, style)
                counts[style] = connection.execute(sql).fetchone()[0]
            self.assertTrue(all(value == counts["not_exists"] for value in counts.values()), counts)
        self.assertEqual(counts["except"], 1)

    def test_except_handles_repeated_outer_key(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript("""
            CREATE TABLE a (id INTEGER);
            CREATE TABLE b (x INTEGER, y INTEGER);
            INSERT INTO a VALUES (1), (2), (NULL), (2);
            INSERT INTO b VALUES (1, 1), (2, NULL), (NULL, 2);
        """)
        sources = [("a", "a"), ("b", "b")]
        conditions = [("a.id = b.x", {"a", "b"}), ("a.id = b.y", {"a", "b"})]
        for style in ("not_exists", "not_in", "left_join", "except"):
            sql = generate.build_sql(sources, conditions, {"b"}, style)
            self.assertEqual(connection.execute(sql).fetchone()[0], 3, style)

    def test_negated_local_column_equality_is_preserved(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript("""
            CREATE TABLE a (id INTEGER);
            CREATE TABLE b (id INTEGER, x INTEGER, y INTEGER);
            INSERT INTO a VALUES (1), (2), (3);
            INSERT INTO b VALUES (1, 10, 10), (2, 10, 11), (3, NULL, NULL);
        """)
        sources = [("a", "a"), ("b", "b")]
        conditions = [("a.id = b.id", {"a", "b"}), ("b.x = b.y", {"b"})]
        for style in ("not_exists", "not_in", "left_join", "except"):
            sql = generate.build_sql(sources, conditions, {"b"}, style)
            self.assertEqual(connection.execute(sql).fetchone()[0], 2, style)


if __name__ == "__main__":
    unittest.main()
