#!/usr/bin/env python3
"""Build nested, post-centered anti-join extensions of CardEst queries."""

from collections import Counter, defaultdict
from pathlib import Path
import csv
import importlib.util
import io


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "stats_CEB.sql"
HELPER = ROOT.parent / "cardest_negation_workload" / "generate.py"
spec = importlib.util.spec_from_file_location("cardest_cq_helpers", HELPER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load CQ helper from {HELPER}")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

# Each relation is correlated to a post already present in the base query.
# The filters distinguish relevant kinds of comments, votes, history and links.
TEMPLATES = (
    ("scored_comments", "comments", "n_c", "n_c.PostId = p.Id", ("n_c.Score >= 1",)),
    ("upvotes", "votes", "n_v", "n_v.PostId = p.Id", ("n_v.VoteTypeId = 2",)),
    ("body_edits", "postHistory", "n_ph", "n_ph.PostId = p.Id",
     ("n_ph.PostHistoryTypeId = 5",)),
    ("linked_posts", "postLinks", "n_pl", "n_pl.PostId = p.Id", ("n_pl.LinkTypeId = 1",)),
    ("incoming_links", "postLinks", "n_pli", "n_pli.RelatedPostId = p.Id",
     ("n_pli.LinkTypeId = 1",)),
    ("owner_badges", "badges", "n_b", "n_b.UserId = p.OwnerUserId", ()),
    ("high_reputation_owner", "users", "n_u", "n_u.Id = p.OwnerUserId",
     ("n_u.Reputation >= 1000",)),
    ("owner_scored_comments", "comments", "n_cu", "n_cu.UserId = p.OwnerUserId",
     ("n_cu.Score >= 1",)),
    ("owner_upvotes", "votes", "n_vu", "n_vu.UserId = p.OwnerUserId",
     ("n_vu.VoteTypeId = 2",)),
    ("owner_body_edits", "postHistory", "n_phu", "n_phu.UserId = p.OwnerUserId",
     ("n_phu.PostHistoryTypeId = 5",)),
)


def select_bases(lines):
    groups = defaultdict(list)
    for number, line in enumerate(lines, 1):
        query, sources, conditions = helper.parse(line)
        if ("posts", "p") not in sources or len(sources) > 4:
            continue
        tables = {table.lower() for table, _ in sources}
        if sum(table.lower() not in tables for _, table, _, _, _ in TEMPLATES) < 4:
            continue
        groups[(len(sources), tuple(sorted(tables)))].append((number, query, sources, conditions))

    # Include the single two-relation post query, all 19 three-relation ones,
    # and select 20 four-relation queries round-robin across relation sets.
    selected = []
    for size, limit in ((2, 1), (3, 19), (4, 20)):
        buckets = [list(groups[key]) for key in sorted(groups) if key[0] == size]
        taken = 0
        while taken < limit:
            progress = False
            for bucket in buckets:
                if bucket and taken < limit:
                    selected.append(bucket.pop(0))
                    taken += 1
                    progress = True
            if not progress:
                raise ValueError(f"Not enough eligible base queries of size {size}")
    return sorted(selected)


def main():
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    bases = select_bases(lines)
    position_counts = [Counter() for _ in range(4)]
    total_counts = Counter()
    sql_lines, cq_lines = [], []
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest, lineterminator="\n")
    writer.writerow(("id", "source_line", "negated_count", "positive_relations",
                     "added_templates", "added_aliases"))

    for number, query, sources, conditions in bases:
        tables = {table.lower() for table, _ in sources}
        candidates = [t for t in TEMPLATES if t[1].lower() not in tables]
        selected = []
        for position in range(4):
            template = min(
                candidates,
                key=lambda t: (
                    t[1].lower() in {item[1].lower() for item in selected},
                    position_counts[position][t[0]],
                    total_counts[t[0]],
                    TEMPLATES.index(t),
                ),
            )
            candidates.remove(template)
            selected.append(template)
            position_counts[position][template[0]] += 1
            total_counts[template[0]] += 1

        for count in range(5):
            active = selected[:count]
            identifier = f"{number}.{count}"
            extra_sources = [(table, alias) for _, table, alias, _, _ in active]
            extra_conditions = []
            clauses = []
            for _, table, alias, join, filters in active:
                terms = (join, *filters)
                clauses.append(f"NOT EXISTS (SELECT 1 FROM {table} as {alias} WHERE "
                               + " AND ".join(terms) + ")")
                for term in terms:
                    extra_conditions.append((term, {a for a, _ in helper.REFERENCE.findall(term)}))
            sql = query[:-1] + "".join(f" AND {clause}" for clause in clauses) + ";"
            cq = helper.build_cq(sources + extra_sources, conditions + extra_conditions,
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
    print("Template counts by sequence position:")
    for position, counts in enumerate(position_counts, 1):
        print(f"  {position}: {dict(counts)}")


if __name__ == "__main__":
    main()
