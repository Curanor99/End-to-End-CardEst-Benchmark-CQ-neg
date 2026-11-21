#!/usr/bin/env python3
"""Build nested anti-join extensions of all CardEst queries."""

from itertools import permutations
from pathlib import Path
import csv
import io
import sys


ROOT = Path(__file__).resolve().parent
# Find the shared module even when invoked directly from another directory.
sys.path.insert(0, str(ROOT.parent))
import negation_common as common


MAX_ADDED = 4
ANCHORS = {
    "post": (("posts", "Id"), ("comments", "PostId"), ("posthistory", "PostId"),
             ("votes", "PostId"), ("postlinks", "PostId"), ("tags", "ExcerptPostId")),
    "user": (("posts", "OwnerUserId"), ("users", "Id"), ("comments", "UserId"),
             ("posthistory", "UserId"), ("votes", "UserId"), ("badges", "UserId")),
}
TEMPLATES = (
    ("scored_comments", "comments", "n_c", "PostId", "post", ("n_c.Score >= 1",)),
    ("upvotes", "votes", "n_v", "PostId", "post", ("n_v.VoteTypeId = 2",)),
    ("body_edits", "postHistory", "n_ph", "PostId", "post",
     ("n_ph.PostHistoryTypeId = 5",)),
    ("linked_posts", "postLinks", "n_pl", "PostId", "post", ("n_pl.LinkTypeId = 1",)),
    ("incoming_links", "postLinks", "n_pli", "RelatedPostId", "post",
     ("n_pli.LinkTypeId = 1",)),
    ("user_badges", "badges", "n_b", "UserId", "user", ()),
    ("high_reputation_user", "users", "n_u", "Id", "user", ("n_u.Reputation >= 1000",)),
    ("user_scored_comments", "comments", "n_cu", "UserId", "user", ("n_cu.Score >= 1",)),
    ("user_upvotes", "votes", "n_vu", "UserId", "user", ("n_vu.VoteTypeId = 2",)),
    ("user_body_edits", "postHistory", "n_phu", "UserId", "user",
     ("n_phu.PostHistoryTypeId = 5",)),
    ("user_scored_posts", "posts", "n_p", "OwnerUserId", "user", ("n_p.Score >= 1",)),
    ("referenced_scored_post", "posts", "n_pid", "Id", "post", ("n_pid.Score >= 1",)),
    ("tag_excerpt", "tags", "n_t", "ExcerptPostId", "post", ()),
)


def eligible_templates(sources):
    aliases = {table.lower(): alias for table, alias in sources}
    anchors = {
        kind: next((f"{aliases[table]}.{column}" for table, column in keys if table in aliases),
                   None)
        for kind, keys in ANCHORS.items()
    }
    return [(name, table, alias, f"{alias}.{column} = {anchors[kind]}", filters)
            for name, table, alias, column, kind, filters in TEMPLATES
            if table.lower() not in aliases and anchors[kind] is not None]


def candidate_sequences(sources):
    candidates = eligible_templates(sources)
    depth = min(MAX_ADDED, len({template[1] for template in candidates}))
    return [order for order in permutations(candidates, depth)
            if len({template[1] for template in order}) == depth]


def template_table(_number, template):
    return template[1]


def main():
    lines = common.SOURCE.read_text(encoding="utf-8").splitlines()
    bases = common.select_bases(lines)
    candidates = {number: candidate_sequences(sources) for number, _, sources, _ in bases}
    unsupported = [number for number, orders in candidates.items() if not orders[0]]
    if unsupported:
        raise ValueError(f"No eligible added-negation template for source lines {unsupported}")
    orders = common.balanced_sequences(
        candidates,
        template_table,
        template_for=lambda template: template[0],
    )
    sql_lines = []
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest, lineterminator="\n")
    writer.writerow(("id", "source_line", "negated_count", "positive_relations",
                     "added_templates", "added_aliases"))

    for number, query, sources, conditions in bases:
        for count in range(len(orders[number]) + 1):
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
            sql_lines.append(f"{identifier}||{sql}")
            writer.writerow((
                identifier, number, count,
                " ".join(f"{table}:{alias}" for table, alias in sources),
                " ".join(template[0] for template in active),
                " ".join(template[2] for template in active),
            ))

    (ROOT / "not_exists.sql").write_text("\n".join(sql_lines) + "\n", encoding="utf-8")
    (ROOT / "manifest.csv").write_text(manifest.getvalue(), encoding="utf-8")
    print(f"Generated {len(sql_lines)} queries from {len(bases)} base queries")
    common.print_table_coverage(orders, template_table)


if __name__ == "__main__":
    main()
