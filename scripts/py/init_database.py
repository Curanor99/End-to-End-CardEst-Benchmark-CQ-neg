
import psycopg2
from pathlib import Path

INDEX_SQL_FILE = "scripts/sql/stats_index.sql"
CREATE_TABLES_SQL_FILE = "datasets/stats_simplified/stats.sql"

DATASET_DIR = Path("datasets/stats_simplified")

TABLES = {
    "badges": "badges.csv",
    "comments": "comments.csv",
    "users": "users.csv",
    "tags": "tags.csv",
    "posts": "posts.csv",
    "votes": "votes.csv",
    "posthistory": "postHistory.csv",
    "postlinks": "postLinks.csv",
}


def get_connection():
    return psycopg2.connect(
        database="benchmark",
        user="postgres",
        password="postgres",
        host="127.0.0.1",
        port=5432,
    )


def load_csv_files(cursor):
    for table, filename in TABLES.items():
        filepath = DATASET_DIR / filename

        print(f"Loading {filepath} into {table}...")

        with open(filepath, "r", encoding="utf-8") as csv_file:
            cursor.copy_expert(
                f"COPY {table} FROM STDIN WITH CSV HEADER",
                csv_file
            )


if __name__ == "__main__":
    conn = get_connection()

    try:
        print("Connection established successfully.")

        with conn:
            with conn.cursor() as cursor:
                print("Creating schema...")
                with open(CREATE_TABLES_SQL_FILE, "r") as create_file:
                    cursor.execute(create_file.read())

                load_csv_files(cursor)

                print("Creating indexes...")
                with open(INDEX_SQL_FILE, "r") as sql_file:
                    cursor.execute(sql_file.read())

        print("Database initialization completed successfully.")

    except Exception as e:
        print(f"Database initialization failed: {e}")

    finally:
        conn.close()
