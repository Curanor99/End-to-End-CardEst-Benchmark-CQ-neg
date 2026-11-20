# CardEst workload: negate the central atom

`not_exists.sql` and `cq.txt` each contain 40 lines in `id||query` format.
Strip the ID and separator before executing SQL. IDs use the 1-based source
line in `stats_CEB.sql`: `<id>.0` is the unchanged base SQL (without its
cardinality prefix) and `<id>.1` immediately follows with one negated atom.
Pairs are emitted in source-line order. `manifest.csv` records the positive
and negated aliases for each query ID.

The generator excludes queries with fewer than three relation atoms, then
selects 20 queries by ascending atom count, SQL text length (including the
semicolon but not the cardinality prefix), and source line. With the current
source file, this selects 20 three-atom queries.
It treats relation aliases as nodes and explicit equality joins as edges,
counting each distinct neighbor once, and checks that the graph is a tree.
The highest-degree atom is negated; ties go to the first alias in `FROM` order.

The selected relation moves into a single correlated `NOT EXISTS` with all
its original filters and joins. All other predicates stay in the outer query.
No new joins are inferred: removing a central atom can leave disconnected
outer relations, so the resulting Cartesian product can be large.

The CQ file follows the other negation workloads' `COUNT_BAG` notation with
query-specific filtered bag projections. Shared variables represent positive
equality joins, and `NOT V_alias(...)` tests whether a matching tuple is absent.
If the negated atom was the only link between two outer columns, those columns
remain independent variables; a repeated column in the negative projection
requires both correlations to match the same row. The views include the
null guards needed to reproduce SQL equality behavior.

To regenerate the artifacts from the repository root, run
`python workloads\cardest_workload_and_protocol\cardest_negate_central_atom\generate.py`.
