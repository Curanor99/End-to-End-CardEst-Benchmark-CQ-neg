#!/usr/bin/env python3
"""Generate CardEst pairs that negate the highest-degree join-tree atom."""

import csv
import io
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
import negation_common as common


BASE_COUNT = 20
MIN_ATOMS = 3


def select_bases(lines):
    bases = []
    for number, line in enumerate(lines, 1):
        query, sources, conditions = common.parse(line)
        if len(sources) >= MIN_ATOMS:
            bases.append((number, query, sources, conditions))
    if len(bases) < BASE_COUNT:
        raise ValueError(f"Expected at least {BASE_COUNT} source queries with {MIN_ATOMS} or more atoms")
    ranked = sorted(bases, key=lambda base: (len(base[2]), len(base[1]), base[0]))
    return sorted(ranked[:BASE_COUNT], key=lambda base: base[0])


def central_atom(sources, conditions):
    neighbors = {alias: set() for _, alias in sources}
    for _, refs in conditions:
        if len(refs) == 2:
            left, right = refs
            neighbors[left].add(right)
            neighbors[right].add(left)

    pending = [next(iter(neighbors))]
    reached = set()
    while pending:
        alias = pending.pop()
        if alias not in reached:
            reached.add(alias)
            pending.extend(neighbors[alias] - reached)
    if (len(reached) != len(neighbors) or len(neighbors) < 2
            or sum(map(len, neighbors.values())) != 2 * (len(neighbors) - 1)):
        raise ValueError(f"Expected a join tree with at least two atoms: {sources}")

    # Dict iteration preserves FROM order, so max keeps the first alias on ties.
    return max(neighbors, key=lambda alias: len(neighbors[alias]))


def build_sql(sources, conditions, central):
    outer, inner = common.split_conditions(conditions, {central})
    positive = ", ".join(f"{table} as {alias}" for table, alias in sources
                         if alias != central)
    table = next(table for table, alias in sources if alias == central)
    outer.append(f"NOT EXISTS (SELECT 1 FROM {table} as {central} WHERE "
                 + " AND ".join(inner[central]) + ")")
    return f"SELECT COUNT(*) FROM {positive} WHERE " + " AND ".join(outer) + ";"


def render(lines):
    sql = []
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest, lineterminator="\n")
    writer.writerow(("id", "source_line", "negated_count", "positive_aliases",
                     "negated_aliases"))
    for number, query, sources, conditions in select_bases(lines):
        central = central_atom(sources, conditions)
        for depth, negative, variant in (
            (0, set(), query),
            (1, {central}, build_sql(sources, conditions, central)),
        ):
            identifier = f"{number}.{depth}"
            sql.append(f"{identifier}||{variant}")
            writer.writerow((identifier, number, depth,
                             " ".join(alias for _, alias in sources if alias not in negative),
                             central if depth else ""))
    return {
        "not_exists.sql": "\n".join(sql) + "\n",
        "manifest.csv": manifest.getvalue(),
    }


def main():
    lines = common.SOURCE.read_text(encoding="utf-8").splitlines()
    artifacts = render(lines)
    for name, contents in artifacts.items():
        (ROOT / name).write_text(contents, encoding="utf-8", newline="\n")
    print(f"Generated {BASE_COUNT} base/negated pairs")


if __name__ == "__main__":
    main()
