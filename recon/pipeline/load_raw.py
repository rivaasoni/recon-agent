"""
Raw loader — Phase 3, Step 1.

Copies the generated files into DuckDB EXACTLY as received:

    data/raw/bank_statement.csv     -> raw.bank_statement
    data/raw/general_ledger.csv     -> raw.general_ledger
    data/raw/documents/DOC-*.txt    -> raw.documents

Design rules (the things a data engineer cares about):

  1. Raw means raw. Every CSV column is loaded as TEXT (VARCHAR). Converting
     "2026-08-03" to a date or "7678.07" to money is a transformation, and
     transformations live in dbt where they are visible and tested.
  2. Idempotent. CREATE OR REPLACE rebuilds each table from scratch, so
     running this twice gives the same result as running it once.
  3. Lineage. Every row records which file it came from and when it loaded.
  4. Explicit allow-list. We load ONLY the files named below. The answer key
     in data/eval/ must never reach the warehouse the agent queries.

Run it:
    python -m recon.pipeline.load_raw
"""

from __future__ import annotations

import duckdb

from recon.config import settings

# The ONLY files this loader will ever read. Table name -> CSV file name.
CSV_TABLES = {
    "bank_statement": "bank_statement.csv",
    "general_ledger": "general_ledger.csv",
}


def check_inputs_exist() -> None:
    """Fail early with a helpful message if the generator hasn't been run."""
    missing = [name for name in CSV_TABLES.values() if not (settings.raw_dir / name).exists()]
    if missing or not any(settings.documents_dir.glob("DOC-*.txt")):
        raise FileNotFoundError(
            f"Raw files not found in {settings.raw_dir} (missing: {missing or 'documents'}).\n"
            "Fix: generate them first:\n"
            "    python -m recon.data_gen.generate"
        )


def load_csv(con: duckdb.DuckDBPyConnection, table: str, file_name: str) -> None:
    """Load one CSV into raw.<table>, every column as text."""
    path = settings.raw_dir / file_name
    # `?` is a placeholder: DuckDB inserts the value safely. Never build SQL
    # by pasting values into the string — that is how SQL injection happens.
    # (The table name can't be a placeholder, but it comes from our own
    # CSV_TABLES dict above, never from user input.)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE raw.{table} AS
        SELECT
            *,
            ? AS _source_file,
            current_timestamp AS _loaded_at
        FROM read_csv(?, header = true, all_varchar = true)
        """,
        [file_name, str(path)],
    )


def load_documents(con: duckdb.DuckDBPyConnection) -> None:
    """Load every supporting document as one row: file name + full text."""
    pattern = str(settings.documents_dir / "DOC-*.txt")
    # read_text() is a built-in DuckDB function that returns one row per file,
    # with columns `filename` (the full path) and `content` (the text).
    con.execute(
        """
        CREATE OR REPLACE TABLE raw.documents AS
        SELECT
            parse_filename(filename) AS file_name,   -- 'DOC-001.txt', not the full path
            content,
            'documents/' || parse_filename(filename) AS _source_file,
            current_timestamp AS _loaded_at
        FROM read_text(?)
        """,
        [pattern],
    )


def load_all() -> dict[str, int]:
    """Load every raw table. Returns {table name: row count}."""
    check_inputs_exist()
    settings.ensure_dirs()

    # `with` closes the connection when the block ends, even if an error
    # occurs. DuckDB allows only ONE writing process per file at a time, so
    # leaving a connection open would lock out dbt in the next step.
    with duckdb.connect(str(settings.duckdb_path)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        for table, file_name in CSV_TABLES.items():
            load_csv(con, table, file_name)
        load_documents(con)

        counts = {}
        for table in [*CSV_TABLES, "documents"]:
            counts[table] = con.execute(f"SELECT count(*) FROM raw.{table}").fetchone()[0]
    return counts


def main() -> None:
    counts = load_all()
    print(f"Loaded into {settings.duckdb_path.relative_to(settings.project_root)}:")
    for table, n in counts.items():
        print(f"  raw.{table:<16} {n:>4} rows")


if __name__ == "__main__":
    main()
