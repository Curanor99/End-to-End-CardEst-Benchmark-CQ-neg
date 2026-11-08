# CardEst negation workload

The four SQL files and `cq.txt` contain the same 580 query IDs in the format
`id||query`, one query per line. The IDs are not part of SQL: strip the prefix
before execution. The SQL uses the input workload's PostgreSQL-style timestamp
casts. `manifest.csv` records the positive and negated relation aliases for
each ID.

The first ID component is the 1-based line number in `stats_CEB.sql`. The
second is the number of negated relations: `.0` is the unchanged original SQL,
`.1` the first derived query, and so on. The source cardinalities were removed;
the original cardinalities are not valid for derived queries.

## Generation and omissions

For each source query, the generator chooses a maximum-size set of relation
aliases with no original join between two members. Ties are broken by the
order of aliases in the original `FROM` clause. Successive variants negate the
first one, then the first two, and so on. Thus each sequence is nested, but it
is only one of the possible sequences.

Every original filter remains attached to its relation, and every original
join remains in its positive or negated scope. A negated relation denotes the
absence of a matching row satisfying its filters **and all its joins to
positive relations**. A join shared by two negated relations cannot be placed
in two independent anti-joins without changing its meaning; these choices are
therefore excluded. For 52 source queries this prevents reaching a single
positive relation. `omitted_ids.txt` lists the missing sequence levels; they
are omitted from all five query files. Other interpretations, such as nested
negation or treating multiple relations as one negated subquery, would produce
different queries.

`NOT IN` checks for null outer keys and excludes null inner keys. `EXCEPT`
likewise handles null outer keys explicitly and uses `EXISTS` to test whether
the outer key tuple survives the difference. These guards are necessary to
match equality-based `NOT EXISTS` under SQL's null semantics. `LEFT JOIN` tests
a join column that must be non-null on a successful equality match, rather than
assuming a nullable column is a primary key. All generated variants have such
a join column, so none requires a further omission from `left_join.sql`.

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

With Python 3, run `python cardest_negation_workload\generate.py` from the parent
directory. It reads the adjacent `stats_CEB.sql` and overwrites the generated
files in this directory. The generator uses only the Python standard library.
