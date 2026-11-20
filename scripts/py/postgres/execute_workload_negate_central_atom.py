from common import get_queries, run_benchmark, REPO_ROOT

WORKLOAD_PATH = (
        REPO_ROOT
        / "workloads"
        / "cardest_workload_and_protocol"
        / "cardest_negate_central_atom"
        / "not_exists.sql"
)
OUTPUT_DIR = REPO_ROOT / "benchmark_results" / "postgres" / "negate_central_atom"


def main():
    queries = get_queries(WORKLOAD_PATH)
    jobs = [
        {"query_id": query_id, "query": query}
        for query_id, query in queries.items()
    ]
    run_benchmark(jobs, OUTPUT_DIR, "postgres")


if __name__ == "__main__":
    main()
