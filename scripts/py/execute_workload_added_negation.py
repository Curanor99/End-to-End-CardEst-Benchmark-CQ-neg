
import csv
import json
import random
import statistics

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2


WORKLOAD_PATH = "workloads/cardest_workload_and_protocol/cardest_added_negation/not_exists_test.sql"

WARMUP_RUNS = 2
MEASURED_RUNS = 10

RANDOM_SEED = 42

OUTPUT_DIR = Path("benchmark_results/added_negation")

def get_connection():
    conn = psycopg2.connect(
        database="benchmark",
        user="postgres",
        password="postgres",
        host="127.0.0.1",
        port=5432,
    )

    conn.autocommit = True

    return conn

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

            query_id = query_id.strip()
            raw_query = raw_query.strip().rstrip(";")

            queries[query_id] = raw_query

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

    actual_rows = root_plan.get("Actual Rows")
    actual_loops = root_plan.get("Actual Loops")

    return {
        "planning_ms": planning_ms,
        "execution_ms": execution_ms,
        "server_total_ms": (
            planning_ms + execution_ms
            if planning_ms is not None and execution_ms is not None
            else None
        ),
        "actual_rows": actual_rows,
        "actual_loops": actual_loops,
        "plan": plan_data,
    }


def main():
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    runs_file = OUTPUT_DIR / f"postgres_runs_{timestamp}.csv"
    summary_file = OUTPUT_DIR / f"postgres_summary_{timestamp}.csv"
    plans_file = OUTPUT_DIR / f"postgres_plans_{timestamp}.jsonl"

    random.seed(RANDOM_SEED)

    jobs = []

    queries = get_queries(WORKLOAD_PATH)

    for query_id, query in queries.items():
        jobs.append({
            "query_id": query_id,
            "query": query,
        })

    print(f"Loaded {len(jobs)} queries.")

    run_records = []

    conn = get_connection()

    try:
        print("Connection established successfully.")

        with conn.cursor() as cursor:
            print("\nStarting warm-up executions...")

            warmup_jobs = jobs.copy()
            random.shuffle(warmup_jobs)

            for warmup_run in range(1, WARMUP_RUNS + 1):

                print(f"Warm-up {warmup_run}/{WARMUP_RUNS}")

                for job in warmup_jobs:
                    try:
                        execute_query(cursor, job["query"])
                    except Exception as e:
                        print(
                            f"Warm-up failed: "
                            f"{job['query_id']}: {e}"
                        )

            print("\nStarting measured executions...")

            for measured_run in range(1, MEASURED_RUNS + 1):

                print(
                    f"Measured run {measured_run}/{MEASURED_RUNS}"
                )

                # Randomize query order for each repetition.
                current_jobs = jobs.copy()
                random.shuffle(current_jobs)

                for job in current_jobs:

                    try:
                        measurements = execute_query(
                            cursor, job["query"]
                        )

                        run_records.append({
                            "timestamp": datetime.now().isoformat(),
                            "query_id": job["query_id"],
                            "run": measured_run,
                            "planning_ms": measurements["planning_ms"],
                            "execution_ms": measurements["execution_ms"],
                            "server_total_ms": measurements["server_total_ms"],
                            "actual_rows": measurements["actual_rows"],
                            "actual_loops": measurements["actual_loops"],
                            "error": "",
                        })

                        with open(
                                plans_file, "a", encoding="utf-8"
                        ) as plan_file:

                            json.dump({
                                "query_id": job["query_id"],
                                "run": measured_run,
                                "plan": measurements["plan"],
                            }, plan_file)

                            plan_file.write("\n")

                    except Exception as e:
                        run_records.append({
                            "timestamp": datetime.now().isoformat(),
                            "query_id": job["query_id"],
                            "run": measured_run,
                            "error": str(e),
                        })

                        print(
                            f"Query failed: "
                            f"{job['query_id']}: {e}"
                        )

        print("\nBenchmark execution completed.")

    finally:
        conn.close()

    columns = [
        "timestamp",
        "query_id",
        "run",
        "planning_ms",
        "execution_ms",
        "server_total_ms",
        "actual_rows",
        "actual_loops",
        "error",
    ]

    with open(runs_file, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(run_records)

    print(f"Individual measurements saved to: {runs_file}")

    grouped = defaultdict(list)

    for record in run_records:

        if not record.get("error"):
            grouped[record["query_id"]].append(record)

    summary_records = []

    for query_id, records in grouped.items():

        summary = {
            "query_id": query_id,
            "successful_runs": len(records),
        }

        for metric in [
            "planning_ms",
            "execution_ms",
            "server_total_ms",
        ]:

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
                statistics.stdev(values)
                if len(values) >= 2
                else 0
            )
            summary[f"{metric}_min"] = min(values)
            summary[f"{metric}_max"] = max(values)

        summary_records.append(summary)

    if summary_records:

        summary_columns = list(dict.fromkeys(
            key
            for record in summary_records
            for key in record.keys()
        ))

        with open(
                summary_file, "w", newline="", encoding="utf-8"
        ) as f:

            writer = csv.DictWriter(
                f, fieldnames=summary_columns
            )

            writer.writeheader()
            writer.writerows(summary_records)

        print(f"Summary statistics saved to: {summary_file}")

    print(f"Execution plans saved to: {plans_file}")


if __name__ == "__main__":
    main()
