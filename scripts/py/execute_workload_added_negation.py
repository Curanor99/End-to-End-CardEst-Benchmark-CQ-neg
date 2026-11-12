
import psycopg2
from pathlib import Path

ADDED_NEGATION_SQL_FILE = "workloads/cardest_workload_and_protocol/cardest_added_negation/not_exists.sql"


def get_connection():
    return psycopg2.connect(
        database="benchmark",
        user="postgres",
        password="postgres",
        host="127.0.0.1",
        port=5432,
    )


def get_queries():
    queries = {}

    with open(ADDED_NEGATION_SQL_FILE, "r") as workload_file:
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

    queries = get_queries()

    try:
        print("Connection established successfully.")

        with conn:
            with conn.cursor() as cursor:
                for query_id in queries.keys():
                    cursor.execute(queries[query_id])
                    result = cursor.fetchall()
                    print(f"{query_id}: {result}")

        print("Workload executed.")

    except Exception as e:
        print(f"Workload execution failed: {e}")

    finally:
        conn.close()
