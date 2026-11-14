from common import get_queries
from scripts.py.postgres.common import get_connection

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
    queries_by_representation = {}

    for representation, relative_path in WORKLOAD_FILES.items():
        queries = get_queries(relative_path)
        for query_id in queries:
            if query_id not in queries_by_representation:
                queries_by_representation[query_id] = {}

            queries_by_representation[query_id][representation] = queries[query_id]

    connection = get_connection(autocommit=True)

    try:
        print("Connection established successfully.")
        with connection.cursor() as cursor:
            print("\nExecuting queries...")

            for query_id in queries_by_representation:
                print(f"Checking for query with id {query_id}...")
                queries = queries_by_representation[query_id]
                expected_result = None

                for representation in queries:
                    cursor.execute(queries[representation])
                    result = cursor.fetchone()[0]

                    if expected_result is None:
                        expected_result = result
                    else:
                        if result != expected_result:
                            raise AssertionError(f"For query with id {query_id} the different representations led to different results.")

                print("Results are equal.")

    except Exception as err:
        print(f"An exception occurred: {err}")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
