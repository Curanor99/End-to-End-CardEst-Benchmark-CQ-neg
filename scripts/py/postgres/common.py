import csv
import json
import os
import random
import statistics

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2


WARMUP_RUNS = 2
MEASURED_RUNS = 10
RANDOM_SEED = 42


def get_connection(autocommit=False):
    connection = psycopg2.connect(
        database="benchmark",
        user="postgres",
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        host="127.0.0.1",
        port=5432,
    )
    connection.autocommit = autocommit
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


def execute_query(cursor, query):
    explain_query = (
        "EXPLAIN "
        "(ANALYZE, FORMAT JSON, TIMING OFF, SUMMARY ON, BUFFERS) "
        + query
    )
    cursor.execute(explain_query)
    result = cursor.fetchone()[0]

    if isinstance(result, str):
        result = json.loads(result)

    plan_data = result[0]
    planning_ms = plan_data.get("Planning Time")
    execution_ms = plan_data.get("Execution Time")
    root_plan = plan_data.get("Plan", {})

    return {
        "planning_ms": planning_ms,
        "execution_ms": execution_ms,
        "server_total_ms": (
            planning_ms + execution_ms
            if planning_ms is not None and execution_ms is not None
            else None
        ),
        "actual_rows": root_plan.get("Actual Rows"),
        "actual_loops": root_plan.get("Actual Loops"),
        "plan": plan_data,
    }


def run_benchmark(jobs, output_dir, output_prefix, include_representation=False):
    Path(output_dir).mkdir(exist_ok=True, parents=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    runs_file = f"{output_dir}/{output_prefix}_runs_{timestamp}.csv"
    summary_file = f"{output_dir}/{output_prefix}_summary_{timestamp}.csv"
    plans_file = f"{output_dir}/{output_prefix}_plans_{timestamp}.jsonl"

    random.seed(RANDOM_SEED)
    print(f"Loaded {len(jobs)} queries.")
    run_records = []
    connection = get_connection(autocommit=True)

    try:
        print("Connection established successfully.")
        with connection.cursor() as cursor:
            print("\nStarting warm-up executions...")
            warmup_jobs = jobs.copy()
            random.shuffle(warmup_jobs)

            for warmup_run in range(1, WARMUP_RUNS + 1):
                print(f"Warm-up {warmup_run}/{WARMUP_RUNS}")
                for job in warmup_jobs:
                    try:
                        execute_query(cursor, job["query"])
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
                        measurements = execute_query(cursor, job["query"])
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
        key = (
            (record["representation"], record["query_id"])
            if include_representation
            else record["query_id"]
        )
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
