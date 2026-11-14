import csv
import json
import random
import statistics
import time

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[3]
DATABASE_FILE = REPO_ROOT / "benchmark_results" / "duckdb" / "benchmark.duckdb"

WARMUP_RUNS = 2
MEASURED_RUNS = 10
RANDOM_SEED = 42


def ensure_duckdb_version():
    if duckdb.__version__ != "2.0.0":
        raise RuntimeError(
            f"DuckDB 2.0.0 is required, found {duckdb.__version__}"
        )


def get_connection():
    ensure_duckdb_version()

    if not DATABASE_FILE.exists():
        raise FileNotFoundError(
            f"DuckDB database not found at {DATABASE_FILE}. "
            "Run scripts/py/duckdb/init_database.py first."
        )

    connection = duckdb.connect(str(DATABASE_FILE))

    connection.execute("SET memory_limit = '16GB'")
    connection.execute("SET threads = 4")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute("SET max_temp_directory_size = '50GB'")

    return connection


def get_queries(file_path):
    queries = {}

    with open(file_path, "r", encoding="utf-8") as workload_file:
        for line_number, line in enumerate(workload_file, start=1):
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            query_id, separator, raw_query = line.partition("||")

            if not separator:
                raise ValueError(
                    f"Invalid query format in {file_path}, "
                    f"line {line_number}"
                )

            queries[query_id.strip()] = raw_query.strip().rstrip(";")

    return queries


def execute_query(connection, query):
    explain_query = "EXPLAIN (FORMAT JSON) " + query
    started_at = time.perf_counter()
    plan_result = connection.execute(explain_query).fetchone()
    planning_ms = (time.perf_counter() - started_at) * 1000
    plan_data = json.loads(plan_result[1])

    started_at = time.perf_counter()
    query_result = connection.execute(query).fetchall()
    execution_ms = (time.perf_counter() - started_at) * 1000
    server_total_ms = planning_ms + execution_ms

    return {
        "planning_ms": planning_ms,
        "execution_ms": execution_ms,
        "server_total_ms": server_total_ms,
        "actual_rows": len(query_result),
        "actual_loops": None,
        "plan": plan_data,
    }


def run_benchmark(jobs, output_dir, output_prefix, include_representation=False):
    output_dir.mkdir(exist_ok=True, parents=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    runs_file = output_dir / f"{output_prefix}_runs_{timestamp}.csv"
    summary_file = output_dir / f"{output_prefix}_summary_{timestamp}.csv"
    plans_file = output_dir / f"{output_prefix}_plans_{timestamp}.jsonl"

    random.seed(RANDOM_SEED)
    print(f"Loaded {len(jobs)} queries.")

    run_records = []
    connection = get_connection()

    try:
        print("Connection established successfully.")
        print("\nStarting warm-up executions...")

        warmup_jobs = jobs.copy()
        random.shuffle(warmup_jobs)

        for warmup_run in range(1, WARMUP_RUNS + 1):
            print(f"Warm-up {warmup_run}/{WARMUP_RUNS}")

            for job in warmup_jobs:
                try:
                    execute_query(connection, job["query"])
                except Exception as error:
                    label = (
                        f'{job["representation"]} {job["query_id"]}'
                        if include_representation
                        else job["query_id"]
                    )
                    print(f"Warm-up failed: {label}: {error}")

        print("\nStarting measured executions...")

        for measured_run in range(1, MEASURED_RUNS + 1):
            print(f"Measured run {measured_run}/{MEASURED_RUNS}")
            current_jobs = jobs.copy()
            random.shuffle(current_jobs)

            for job in current_jobs:
                record = {
                    "timestamp": datetime.now().isoformat(),
                    "query_id": job["query_id"],
                    "run": measured_run,
                }
                plan_record = {
                    "query_id": job["query_id"],
                    "run": measured_run,
                }

                if include_representation:
                    record["representation"] = job["representation"]
                    plan_record["representation"] = job["representation"]

                try:
                    measurements = execute_query(connection, job["query"])
                    record.update({
                        "planning_ms": measurements["planning_ms"],
                        "execution_ms": measurements["execution_ms"],
                        "server_total_ms": measurements["server_total_ms"],
                        "actual_rows": measurements["actual_rows"],
                        "actual_loops": measurements["actual_loops"],
                        "error": "",
                    })
                    plan_record["plan"] = measurements["plan"]

                    with open(plans_file, "a", encoding="utf-8") as plan_file:
                        json.dump(plan_record, plan_file)
                        plan_file.write("\n")

                except Exception as error:
                    record["error"] = str(error)
                    label = (
                        f'{job["representation"]} {job["query_id"]}'
                        if include_representation
                        else job["query_id"]
                    )
                    print(f"Query failed: {label}: {error}")

                run_records.append(record)

        print("\nBenchmark execution completed.")
    finally:
        connection.close()

    columns = ["timestamp"]
    if include_representation:
        columns.append("representation")
    columns.extend([
        "query_id",
        "run",
        "planning_ms",
        "execution_ms",
        "server_total_ms",
        "actual_rows",
        "actual_loops",
        "error",
    ])

    with open(runs_file, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(run_records)

    print(f"Individual measurements saved to: {runs_file}")

    grouped = defaultdict(list)
    for record in run_records:
        if record.get("error"):
            continue
        key = (record["representation"], record["query_id"]) if (
            include_representation
        ) else record["query_id"]
        grouped[key].append(record)

    summary_records = []
    for key, records in grouped.items():
        if include_representation:
            representation, query_id = key
            summary = {
                "representation": representation,
                "query_id": query_id,
                "successful_runs": len(records),
            }
        else:
            summary = {
                "query_id": key,
                "successful_runs": len(records),
            }

        for metric in ("planning_ms", "execution_ms", "server_total_ms"):
            values = [
                record[metric]
                for record in records
                if record.get(metric) is not None
            ]
            if not values:
                continue

            summary[f"{metric}_mean"] = statistics.mean(values)
            summary[f"{metric}_median"] = statistics.median(values)
            summary[f"{metric}_stddev"] = (
                statistics.stdev(values) if len(values) >= 2 else 0
            )
            summary[f"{metric}_min"] = min(values)
            summary[f"{metric}_max"] = max(values)

        summary_records.append(summary)

    if summary_records:
        summary_columns = list(dict.fromkeys(
            key for record in summary_records for key in record
        ))
        with open(summary_file, "w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=summary_columns)
            writer.writeheader()
            writer.writerows(summary_records)
        print(f"Summary statistics saved to: {summary_file}")

    print(f"Execution plans saved to: {plans_file}")
