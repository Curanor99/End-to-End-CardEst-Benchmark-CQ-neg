#!/usr/bin/env python3
"""Build nested, post-centered anti-join extensions of CardEst queries."""

from itertools import permutations
from pathlib import Path
import csv
import io
import sys


ROOT = Path(__file__).resolve().parent
# Find the shared module even when invoked directly from another directory.
sys.path.insert(0, str(ROOT.parent))
import negation_common as common


def candidate_sequences(sources):
    tables = {table.lower() for table, _ in sources}
    candidates = common.eligible_templates(tables)
    distinct = min(common.ADDED_COUNT, len({template[1].lower() for template in candidates}))
    return [order for order in permutations(candidates, common.ADDED_COUNT)
            if len({template[1].lower() for template in order}) == distinct]


def template_table(_number, template):
    return template[1]


def main():
    lines = common.SOURCE.read_text(encoding="utf-8").splitlines()
    bases = common.select_bases(lines)
    orders = common.balanced_sequences(
        {number: candidate_sequences(sources) for number, _, sources, _ in bases},
        template_table,
        template_for=lambda template: template[0],
    )
    sql_lines, cq_lines = [], []
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest, lineterminator="\n")
    writer.writerow(("id", "source_line", "negated_count", "positive_relations",
                     "added_templates", "added_aliases"))

    for number, query, sources, conditions in bases:
        for count in range(common.ADDED_COUNT + 1):
            active = orders[number][:count]
            identifier = f"{number}.{count}"
            extra_sources = [(table, alias) for _, table, alias, _, _ in active]
            extra_conditions = []
            clauses = []
            for _, table, alias, join, filters in active:
                terms = (join, *filters)
                clauses.append(f"NOT EXISTS (SELECT 1 FROM {table} as {alias} WHERE "
                               + " AND ".join(terms) + ")")
                for term in terms:
                    extra_conditions.append((term, {a for a, _ in common.REFERENCE.findall(term)}))
            sql = query[:-1] + "".join(f" AND {clause}" for clause in clauses) + ";"
            cq = common.build_cq(sources + extra_sources, conditions + extra_conditions,
                                 {alias for _, _, alias, _, _ in active})
            sql_lines.append(f"{identifier}||{sql}")
            cq_lines.append(f"{identifier}||{cq}")
            writer.writerow((
                identifier, number, count,
                " ".join(f"{table}:{alias}" for table, alias in sources),
                " ".join(template[0] for template in active),
                " ".join(template[2] for template in active),
            ))

    (ROOT / "not_exists.sql").write_text("\n".join(sql_lines) + "\n", encoding="utf-8")
    (ROOT / "cq.txt").write_text("\n".join(cq_lines) + "\n", encoding="utf-8")
    (ROOT / "manifest.csv").write_text(manifest.getvalue(), encoding="utf-8")
    print(f"Generated {len(sql_lines)} queries from {len(bases)} base queries")
    common.print_table_coverage(orders, template_table)


if __name__ == "__main__":
    main()
