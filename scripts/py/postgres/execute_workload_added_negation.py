from common import get_queries, run_benchmark


WORKLOAD_PATH = "workloads/cardest_workload_and_protocol/cardest_added_negation/not_exists.sql"
OUTPUT_DIR = f"benchmark_results/postgres/added_negation"


def main():
    queries = get_queries(WORKLOAD_PATH)
    jobs = [
        {"query_id": query_id, "query": query}
        for query_id, query in queries.items()
    ]
    run_benchmark(jobs, OUTPUT_DIR, "postgres")


if __name__ == "__main__":
    main()
