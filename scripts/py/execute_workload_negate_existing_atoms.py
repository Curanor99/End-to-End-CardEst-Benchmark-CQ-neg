
import psycopg2
from pathlib import Path

EXCEPT_SQL_FILE = "workloads/cardest_workload_and_protocol/cardest_negate_existing_atoms/except.sql"
LEFT_JOIN_SQL_FILE = "workloads/cardest_workload_and_protocol/cardest_negate_existing_atoms/left_join.sql"
NOT_EXISTS_SQL_FILE = "workloads/cardest_workload_and_protocol/cardest_negate_existing_atoms/not_exists.sql"
NOT_IN_SQL_FILE = "workloads/cardest_workload_and_protocol/cardest_negate_existing_atoms/not_in.sql"


def get_connection():
    return psycopg2.connect(
        database="benchmark",
        user="postgres",
        password="postgres",
        host="127.0.0.1",
        port=5432,
    )


def get_queries(file_path):
    queries = {}

    with open(file_path, "r") as workload_file:
        line = workload_file.readline()
        while line is not None and line != "":
            line_parts = line.split("||")

            query_id = line_parts[0]
            raw_query = line_parts[1].replace("\n", "")

            queries[query_id] = f"EXPLAIN ANALYZE {raw_query}"

            line = workload_file.readline()

    return queries


if __name__ == "__main__":
    conn = get_connection()

    queries_except = get_queries(EXCEPT_SQL_FILE)
    queries_left_join = get_queries(LEFT_JOIN_SQL_FILE)
    queries_not_exists = get_queries(NOT_EXISTS_SQL_FILE)
    queries_not_in = get_queries(NOT_IN_SQL_FILE)

    try:
        print("Connection established successfully.")

        with conn:
            with conn.cursor() as cursor:
                print("\n NOT EXISTS \n")
                for query_id in queries_not_exists.keys():
                    cursor.execute(queries_not_exists[query_id])
                    result = cursor.fetchall()
                    print(f"{query_id}: {result}")

                print("\n EXCEPT \n")
                for query_id in queries_except.keys():
                    cursor.execute(queries_except[query_id])
                    result = cursor.fetchall()
                    print(f"{query_id}: {result}")

                print("\n LEFT JOIN \n")

                for query_id in queries_left_join.keys():
                    cursor.execute(queries_left_join[query_id])
                    result = cursor.fetchall()
                    print(f"{query_id}: {result}")

                print("\n NOT IN \n")
                for query_id in queries_not_in.keys():
                    cursor.execute(queries_not_in[query_id])
                    result = cursor.fetchall()
                    print(f"{query_id}: {result}")

        print("Workload executed.")

    except Exception as e:
        print(f"Workload execution failed: {e}")

    finally:
        conn.close()
