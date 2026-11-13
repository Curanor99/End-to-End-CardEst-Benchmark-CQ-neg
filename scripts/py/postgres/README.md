# PostgreSQL benchmark scripts

These scripts initialize the benchmark database and run the negation workloads
against PostgreSQL. From the repository root, install the dependency and run:

```powershell
python -m pip install -r scripts/py/postgres/requirements.txt
python scripts/py/postgres/init_database.py
python scripts/py/postgres/execute_workload_negate_existing_atoms.py
python scripts/py/postgres/execute_workload_added_negation.py
```

The scripts connect to `benchmark` on `127.0.0.1:5432` as user `postgres`.
Set `POSTGRES_PASSWORD` to override the default password (`postgres`):

```powershell
$env:POSTGRES_PASSWORD = "your-password"
```

`postgres_common.py` contains the shared connection, workload parsing, query
execution, warm-up/measurement loop, and CSV/JSONL reporting logic. Individual
scripts define their workload inputs and output directory. Results are written
under `benchmark_results/postgres/`.
