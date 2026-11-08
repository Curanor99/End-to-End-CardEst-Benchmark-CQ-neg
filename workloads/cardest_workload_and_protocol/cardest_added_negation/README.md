# CardEst workload with additional negated atoms

`not_exists.sql` and `cq.txt` each contain 200 lines in the form `id||query`.
Remove the ID and separator before executing SQL. `manifest.csv` identifies the
base relations and added negation templates for every query.

There are 40 original CardEst queries, each followed by four nested
extensions. In `N.K`, `N` is the 1-based source line and `K` is the number of
added negative atoms: `.0` is the unmodified base SQL, `.1` adds one
`NOT EXISTS`, and each following level retains all previous conditions and
adds one more. Original cardinalities are omitted and must be measured again.
IDs have the same form as in the other workload, but derived queries with the
same ID in the two folders are **different**; include the workload name when
combining results.

## Design

All selected base queries contain `posts as p`. They comprise one 2-relation,
19 3-relation, and 20 4-relation queries. Four-relation queries are selected
round-robin across sets of positive relation names. Added atoms use these
post-related conditions:

| Template | The negated condition rules out |
|---|---|
| `scored_comments` | A comment on the post with score at least 1 |
| `upvotes` | A vote of type 2 on the post |
| `body_edits` | A post-history entry of type 5 for the post |
| `linked_posts` | A type-1 link originating at the post |
| `incoming_links` | A type-1 link whose related post is the post |
| `owner_badges` | A badge belonging to the post's owner |
| `high_reputation_owner` | An owner with reputation at least 1,000 |
| `owner_scored_comments` | A comment by the owner with score at least 1 |
| `owner_upvotes` | A type-2 vote by the owner |
| `owner_body_edits` | A type-5 post-history entry by the owner |

These type values are commonly used for upvotes, body edits, and linked posts
in the Stack Exchange schema; verify the codes against the dataset version used
for an experiment. Owner-related conditions use `p.OwnerUserId`. If that value
is NULL, equality finds no matching owner row and the corresponding negation
holds, as in SQL.

A template is eligible only when its table is absent from the positive base
query, avoiding direct contradictions with a positive occurrence of the same
table. The generator prefers distinct tables within a sequence; if necessary,
it can use two differently correlated atoms over the same table, such as
comments on the post and comments by its owner. Among eligible templates it
balances usage by position and then overall usage, with a deterministic
tie-break. Availability constraints mean that the balance is not exact.

The positive query is held fixed across a sequence, but the added filters can
change result cardinality and selectivity substantially. They do not isolate
the cost of an extra anti-join from that change. The workload is not calibrated
against the actual dataset: measure cardinalities, individual anti-join
selectivities and plans, and check for empty or near-tautological variants.
In particular, owner-level predicates may behave differently for missing
owners, and sequential filters can become increasingly selective.

## CQ notation

Each line gives a formula followed by its query-specific filtered projection
definitions. `V_alias(...)` is a positive atom, `NOT V_alias(...)` is a
negated atom, and shared variables express joins. Every variable in a negative
atom also occurs in a positive one. Projections are positional and retain
duplicates; `COUNT_BAG` counts matching combinations of positive rows, while a
negative atom tests absence. Null guards in the views reproduce SQL equality
semantics.

These atoms represent **filtered, projected relations**, not complete base
tables. Consequently, structural properties computed from these CQ
representations depend on that modeling choice. SQL bag counting is also
different from Boolean query evaluation under ordinary CQ set semantics.

## Reproduction

From the parent folder, run `python cardest_added_negation\generate.py`.
The generator reads `stats_CEB.sql` and reuses the CQ construction helper in
`cardest_negation_workload\generate.py`; both must remain in their current
relative locations. It uses only Python's standard library and overwrites the
generated files in this folder.
