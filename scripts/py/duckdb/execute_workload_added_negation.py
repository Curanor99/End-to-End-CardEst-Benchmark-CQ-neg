from common import REPO_ROOT, get_queries, run_benchmark


WORKLOAD_PATH = (
    REPO_ROOT
    / "workloads"
    / "cardest_workload_and_protocol"
    / "cardest_added_negation"
    / "not_exists.sql"
)
OUTPUT_DIR = REPO_ROOT / "benchmark_results" / "duckdb" / "added_negation"


def main():
    queries = get_queries(WORKLOAD_PATH)
    jobs = [
        {"query_id": query_id, "query": query}
        for query_id, query in queries.items()
    ]
    run_benchmark(jobs, OUTPUT_DIR, "duckdb")


if __name__ == "__main__":
    main()
