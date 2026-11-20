from common import get_connection, REPO_ROOT

CREATE_TABLES_SQL_FILE = REPO_ROOT / "scripts" / "sql" / "stats.sql"
INDEX_SQL_FILE = REPO_ROOT / "scripts" / "sql" / "stats_index.sql"
DATASET_DIR = REPO_ROOT / "datasets" / "stats_simplified"

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


def load_csv_files(cursor):
    for table, filename in TABLES.items():
        filepath = f"{DATASET_DIR}/{filename}"
        print(f"Loading {filepath} into {table}...")

        with open(filepath, "r", encoding="utf-8") as csv_file:
            cursor.copy_expert(
                f"COPY {table} FROM STDIN WITH CSV HEADER",
                csv_file,
            )


def main():
    connection = get_connection()
    try:
        print("Connection established successfully.")
        with connection:
            with connection.cursor() as cursor:
                with open(CREATE_TABLES_SQL_FILE, "r") as create_file:
                    print("Creating schema...")
                    cursor.execute(create_file.read())

                load_csv_files(cursor)

                with open(INDEX_SQL_FILE, "r") as index_file:
                    print("Creating indexes...")
                    cursor.execute(index_file.read())

        print("Database initialization completed successfully.")
    except Exception as error:
        print(f"Database initialization failed: {error}")
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
