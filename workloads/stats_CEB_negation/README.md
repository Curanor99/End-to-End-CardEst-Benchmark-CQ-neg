# Negation benchmark workload

Each `.txt` file has one `id||query` entry per line. The first ID component is
the 1-based position in the supplied workload, including repeated queries. The
second component is the number of negated relational atoms: `.0` is the
unchanged base SQL query, `.1` is the first derived query, and so on. IDs
identify the same variant across all five files.

The sequence is deterministic. A smallest set of positive relations covering
all join-variable equivalence classes is selected; ties are broken by the
lexicographically earliest sequence of relation positions to negate. Relations
outside that set are negated in their original `FROM` order. Every input in
this workload can reach a single positive relation. Original relation-local
conditions apply inside the corresponding negated relation, and equalities
between columns are propagated through their original equality classes.

The SQL forms count positive **row combinations**, preserving the original
`COUNT(*)` bag semantics. Each negation tests for the absence of a matching
filtered row and does not multiply the count. `NOT IN` explicitly handles NULL
join keys to match the `NOT EXISTS` equality semantics. `LEFT JOIN` tests a
join-key column, which cannot be NULL on a successful equality match; every
variant in this workload is applicable. The `EXCEPT` form subtracts matching
existence markers, rather than projected positive rows, so duplicate positive
rows are not lost. The timestamp casts in the original workload use
PostgreSQL-style syntax; check dialect compatibility before running on another
DBMS.

## CQ notation

The CQ file uses filtered, projected **derived predicates**. For example,
`badges as b[b.Date <= T]{UserId=x1}` denotes the projection of
`SELECT b.UserId FROM badges AS b WHERE b.Date <= T` onto `UserId`, with the
result bound to `x1`. `TRUE` means no local filter. `AND` joins literals and
`NOT` negates a literal. Repeated `x` variables denote the original join
equalities; each variable in a negative literal also occurs in a positive
literal. Conditions within brackets are part of the predicate definition, not
free variables in the CQ. This notation is a compact definition of the
predicates, rather than SQL or a full-schema CQ.

Under classical set semantics these are safe CQ bodies over the derived
predicates, and their hypergraphs describe the projected predicates, **not**
the original full database schema. They do not encode the SQL count by
themselves: projecting under set semantics can collapse rows, whereas SQL
counts positive row combinations. Classical CQs also do not model SQL NULL;
the SQL files consistently use SQL's equality and NULL behavior. For exact
structural or cardinality comparisons, explicitly document the interpretation
of projection, duplicate rows, and NULL values.
