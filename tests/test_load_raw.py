"""Tests for the Phase 3 raw loader.

Every test uses the temp_settings fixture (tests/conftest.py), so it
generates data and builds a DuckDB file inside a throwaway folder — never
your real data/processed/recon.duckdb.
"""

import duckdb
import pandas as pd
import pytest

from recon.data_gen import generate
from recon.pipeline.load_raw import load_all


@pytest.fixture
def loaded(temp_settings):
    """Generate the synthetic data, load it, and hand back a read-only connection."""
    generate.main()
    load_all()
    con = duckdb.connect(str(temp_settings.duckdb_path), read_only=True)
    yield con          # the test runs here...
    con.close()        # ...then this cleanup runs, even if the test failed


def test_row_counts_match_the_files(loaded, temp_settings):
    """Nothing dropped or duplicated on the way in."""
    for table, file_name in [("bank_statement", "bank_statement.csv"),
                             ("general_ledger", "general_ledger.csv")]:
        expected = len(pd.read_csv(temp_settings.raw_dir / file_name))
        actual = loaded.execute(f"select count(*) from raw.{table}").fetchone()[0]
        assert actual == expected, f"raw.{table}: {actual} rows, file has {expected}"

    expected_docs = len(list(temp_settings.documents_dir.glob("DOC-*.txt")))
    actual_docs = loaded.execute("select count(*) from raw.documents").fetchone()[0]
    assert actual_docs == expected_docs


def test_raw_columns_are_all_text(loaded):
    """Raw means raw: typing happens in dbt, not in the loader.
    (_loaded_at is the one exception — the loader creates it, it isn't data.)"""
    rows = loaded.execute(
        """
        select table_name, column_name, data_type
        from information_schema.columns
        where table_schema = 'raw' and column_name <> '_loaded_at'
        """
    ).fetchall()
    not_text = [(t, c, d) for t, c, d in rows if d != "VARCHAR"]
    assert not not_text, f"Non-text raw columns: {not_text}"


def test_loading_twice_does_not_duplicate_rows(temp_settings):
    """Idempotency: CREATE OR REPLACE means run 2 == run 1."""
    generate.main()
    first = load_all()
    second = load_all()
    assert first == second


def test_answer_key_never_reaches_the_warehouse(loaded):
    """The most important guarantee in this file.

    If the agent could query the answer key, every Phase 8 accuracy score
    would be meaningless. We check three ways it could leak.
    """
    # 1. No table anywhere with 'answer' in its name.
    tables = [t for (t,) in loaded.execute(
        "select table_schema || '.' || table_name from information_schema.tables"
    ).fetchall()]
    assert not [t for t in tables if "answer" in t.lower()], tables

    # 2. No private ground-truth columns.
    columns = {c for (c,) in loaded.execute(
        "select column_name from information_schema.columns"
    ).fetchall()}
    assert not columns & set(generate.PRIVATE_COLUMNS)

    # 3. No exception ID (EXC-01 ...) in ANY cell of any raw table.
    #    Plain pandas on purpose: pull the table, turn every cell into text,
    #    and search each one. Easy to read, easy to trust.
    for table in ("bank_statement", "general_ledger", "documents"):
        df = loaded.execute(f"select * from raw.{table}").df()
        leaked = df.astype(str).apply(lambda col: col.str.contains("EXC-")).any().any()
        assert not leaked, f"raw.{table} contains an exception ID"


def test_missing_inputs_give_a_helpful_error(temp_settings):
    """Loading before generating should say HOW to fix it, not just crash."""
    with pytest.raises(FileNotFoundError, match="python -m recon.data_gen.generate"):
        load_all()
