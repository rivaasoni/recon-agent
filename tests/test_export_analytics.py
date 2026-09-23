"""Tests for the Phase 9 Power BI export.

The analytics tables are built by dbt, which these tests do not run — so we
create a small stand-in `analytics` schema and check the EXPORT behaves:
every listed table becomes a .parquet and a .csv, with the same rows.
"""

import duckdb
import pandas as pd
import pytest

from recon.pipeline import export_analytics
from recon.pipeline.export_analytics import ANALYTICS_TABLES, export_all


@pytest.fixture
def analytics_tables(temp_settings):
    """A stand-in analytics schema with one row per table."""
    temp_settings.processed_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(temp_settings.duckdb_path)) as con:
        con.execute("create schema analytics")
        for table in ANALYTICS_TABLES:
            con.execute(f"""
                create table analytics.{table} as
                select '{table}' as name, 2 as cases, 0.5 as some_rate,
                       123.45::decimal(12,2) as some_value
            """)
    return temp_settings


def test_every_table_is_exported_as_parquet_and_csv(analytics_tables):
    counts = export_all()

    folder = analytics_tables.processed_dir / "analytics"
    for table in ANALYTICS_TABLES:
        assert (folder / f"{table}.parquet").exists()
        assert (folder / f"{table}.csv").exists()
        assert counts[table] == 1


def test_exported_files_hold_the_same_data(analytics_tables):
    export_all()
    folder = analytics_tables.processed_dir / "analytics"

    csv = pd.read_csv(folder / "metrics_agent_runs.csv")
    parquet = pd.read_parquet(folder / "metrics_agent_runs.parquet")

    assert list(csv["name"]) == ["metrics_agent_runs"]
    assert len(csv) == len(parquet) == 1
    # Parquet keeps types; CSV is text with a header.
    assert parquet["cases"].dtype.kind in "iu"


def test_a_readme_explains_the_files(analytics_tables):
    export_all()
    readme = (analytics_tables.processed_dir / "analytics" / "README.md").read_text()

    assert "Power BI" in readme
    for table in ANALYTICS_TABLES:
        assert table in readme
    # The ground-truth boundary must be stated where someone building a
    # dashboard will see it.
    assert "Ground truth only exists because" in readme


def test_exporting_twice_overwrites_rather_than_appends(analytics_tables):
    export_all()
    first = (analytics_tables.processed_dir / "analytics" / "metrics_agent_runs.csv").read_text()
    export_all()
    second = (analytics_tables.processed_dir / "analytics" / "metrics_agent_runs.csv").read_text()
    assert first == second


def test_export_lists_tables_explicitly(analytics_tables):
    """An allow-list, so a scratch table in the analytics schema can't be
    published by accident."""
    with duckdb.connect(str(analytics_tables.duckdb_path)) as con:
        con.execute("create table analytics.scratch_workings as select 1 as x")

    export_all()

    folder = analytics_tables.processed_dir / "analytics"
    assert not (folder / "scratch_workings.csv").exists()
