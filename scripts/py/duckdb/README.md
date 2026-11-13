# DuckDB benchmark scripts

These scripts run the CardEst negation workloads with DuckDB 2.0.0. From the
repository root:

```powershell
python -m pip install -r scripts/py/duckdb/requirements.txt
python scripts/py/duckdb/init_database.py
python scripts/py/duckdb/execute_workload_negate_existing_atoms.py
python scripts/py/duckdb/execute_workload_added_negation.py
```

Initialization reads the existing CSV dataset and stores the database at
`benchmark_results/duckdb/benchmark.duckdb`. Benchmark runs and JSON query
plans are written under `benchmark_results/duckdb/`.

The workload SQL files are usable unchanged in DuckDB 2.0.0, including the
four negate-existing-atoms representations and the added-negation workload.
The PostgreSQL dataset schema and index SQL are not directly portable:
DuckDB does not accept PostgreSQL `SERIAL` columns or `USING btree` index
syntax. Equivalent DuckDB SQL is provided in `scripts/sql/duckdb/`; the
initializer also replaces the PostgreSQL `\copy` commands with DuckDB CSV
imports.

The runners time planning (`EXPLAIN (FORMAT JSON)`) and query execution
separately with wall-clock measurements and save the physical plan as JSON.
This avoids a DuckDB 2.0.0 issue where `EXPLAIN (ANALYZE, FORMAT JSON)` returns
an error-shaped profile for some table-backed aggregate queries. `actual_rows`
is the number of result rows, and `actual_loops` is left blank because DuckDB
does not report PostgreSQL-style loop counts.
