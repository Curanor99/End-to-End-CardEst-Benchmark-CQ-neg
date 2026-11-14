# CardEst negation workload

The four SQL files and `cq.txt` contain the same 131 query IDs in the format
`id||query`, one query per line. The IDs are not part of SQL: strip the prefix
before execution. The SQL uses the input workload's PostgreSQL-style timestamp
casts. `manifest.csv` records the positive and negated relation aliases for
each ID.

The first ID component is the 1-based line number in `stats_CEB.sql`. The
second is the number of negated relations: `.0` is the unchanged original SQL,
`.1` the first derived query, and so on. The source cardinalities were removed;
the original cardinalities are not valid for derived queries.

## Generation and omissions

The generator uses the same 40 source queries as the added-negation workload.
For each query it finds a longest sequence of negations for which the positive
join graph remains connected at every level and no original join connects two
negated aliases. Ties are broken by the original `FROM` order. Successive
variants negate the first alias, then the first two, and so on; this is only
one of the possible sequences.

Negating a bridge relation can disconnect the positive join graph and produce
a Cartesian product. The connectivity restriction avoids generating such
variants, but does not guarantee that all remaining queries are fast. The
selected aliases for some IDs changed when this restriction was added: do not
compare derived-query results across generator versions by ID alone.

Every original filter remains attached to its relation, and every original
join remains in its positive or negated scope. A negated relation denotes the
absence of a matching row satisfying its filters **and all its joins to
positive relations**. A join shared by two negated relations cannot be placed
in two independent anti-joins without changing its meaning; these choices are
therefore excluded. These restrictions prevent eight source queries from
reaching a single positive relation. `omitted_ids.txt` lists the missing
sequence levels; they are omitted from all five query files. Other
interpretations, such as nested negation or treating multiple relations as one
negated subquery, would produce different queries.

`NOT IN` checks for null outer keys, excludes null inner keys, and uses
`DISTINCT` to reduce the size of its membership set. `EXCEPT` subtracts each
negative relation's key tuples from a set of candidate positive key tuples and
tests membership in the result. Candidate keys come from the positive
relations supplying the anti-join keys, with their applicable positive
filters. The outer query retains the original positive joins and their bag
multiplicity. Null outer keys are accepted explicitly because they cannot
match SQL equality joins. The set difference is uncorrelated, avoiding a
repeated difference for every positive row; computing it still has a cost.
`LEFT JOIN` tests a join column that must be non-null on a successful equality
match, rather than assuming a nullable column is a primary key.

## CQ notation

Each CQ line is self-contained: the formula comes first, followed by its
query-specific view definitions. `FILTER` applies the indicated SQL
conditions; `PROJECT_BAG` projects the listed columns **by position**, retaining
duplicate rows. A column can occur more than once in a projection. `V_alias`
denotes that filtered, projected relation, and `NOT V_alias(...)` denotes
absence of its tuple. Variables shared between positive atoms encode their
equality joins. Every variable in a negative atom also occurs in a positive
atom. Added `IS NOT NULL` view filters reproduce SQL equality behavior.

`COUNT_BAG` counts matching combinations of positive view rows, using their
multiplicities; negated views are tested only for membership. This annotation
is needed to match SQL `COUNT(*)`. Ordinary theoretical CQs normally use set
semantics, and the thesis's Boolean-query tractability results concern
existence, not this bag count. For structural analysis, the atoms here refer
to **query-specific filtered projections**, not the full original relation
schemas; report that modeling choice when computing hypergraphs or width.

## Reproduction

From the repository root, run
`python workloads\cardest_workload_and_protocol\cardest_negate_existing_atoms\generate.py`.
It reads `workloads\stats_CEB\stats_CEB.sql` and overwrites the generated files
in this directory. The generator uses only the Python standard library.
