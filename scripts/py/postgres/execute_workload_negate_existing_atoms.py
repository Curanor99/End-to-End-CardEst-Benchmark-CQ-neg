from common import get_queries, run_benchmark


WORKLOAD_FILES = {
    "NOT_EXISTS": (
        "workloads/cardest_workload_and_protocol/"
        "cardest_negate_existing_atoms/not_exists.sql"
    ),
    "EXCEPT": (
        "workloads/cardest_workload_and_protocol/"
        "cardest_negate_existing_atoms/except.sql"
    ),
    "LEFT_JOIN": (
        "workloads/cardest_workload_and_protocol/"
        "cardest_negate_existing_atoms/left_join.sql"
    ),
    "NOT_IN": (
        "workloads/cardest_workload_and_protocol/"
        "cardest_negate_existing_atoms/not_in.sql"
    ),
}

OUTPUT_DIR = "benchmark_results/postgres/negate_existing_atoms"


def main():
    jobs = []
    for representation, relative_path in WORKLOAD_FILES.items():
        queries = get_queries(relative_path)
        jobs.extend(
            {
                "representation": representation,
                "query_id": query_id,
                "query": query,
            }
            for query_id, query in queries.items()
        )

    run_benchmark(
        jobs,
        OUTPUT_DIR,
        "postgres",
        include_representation=True,
    )


if __name__ == "__main__":
    main()
