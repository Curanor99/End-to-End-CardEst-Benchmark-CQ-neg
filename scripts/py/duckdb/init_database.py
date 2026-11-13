import duckdb

from common import DATABASE_FILE, REPO_ROOT, ensure_duckdb_version


CREATE_TABLES_SQL_FILE = REPO_ROOT / "scripts" / "sql" / "duckdb" / "stats.sql"
INDEX_SQL_FILE = REPO_ROOT / "scripts" / "sql" / "duckdb" / "stats_index.sql"
DATASET_DIR = REPO_ROOT / "datasets" / "stats_simplified"

TABLES = {
    "badges": "badges.csv",
    "comments": "comments.csv",
    "users": "users.csv",
    "tags": "tags.csv",
    "posts": "posts.csv",
    "votes": "votes.csv",
    "postHistory": "postHistory.csv",
    "postLinks": "postLinks.csv",
}


def copy_csv(connection, table, filename):
    filepath = (DATASET_DIR / filename).resolve()
    if not filepath.is_file():
        raise FileNotFoundError(f"Dataset file not found: {filepath}")

    escaped_path = str(filepath).replace("'", "''")
    print(f"Loading {filepath} into {table}...")
    connection.execute(
        f"COPY {table} FROM '{escaped_path}' (HEADER, DELIMITER ',')"
    )


def main():
    ensure_duckdb_version()
    DATABASE_FILE.parent.mkdir(exist_ok=True, parents=True)
    connection = duckdb.connect(str(DATABASE_FILE))
    transaction_started = False

    try:
        print("Connection established successfully.")
        connection.execute("BEGIN TRANSACTION")
        transaction_started = True

        print("Creating schema...")
        connection.execute(CREATE_TABLES_SQL_FILE.read_text(encoding="utf-8"))

        for table in TABLES:
            connection.execute(f"DELETE FROM {table}")

        for table, filename in TABLES.items():
            copy_csv(connection, table, filename)

        print("Creating indexes and refreshing statistics...")
        connection.execute(INDEX_SQL_FILE.read_text(encoding="utf-8"))
        connection.execute("COMMIT")
        transaction_started = False
        print("Database initialization completed successfully.")

    except Exception:
        if transaction_started:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
