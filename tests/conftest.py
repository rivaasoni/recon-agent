"""Shared test fixtures.

pytest automatically loads a file named conftest.py and makes its fixtures
available to every test file in this folder — no import needed.
"""

import dataclasses

import pytest

from recon.config import settings
from recon.data_gen import documents, generate
from recon.mcp_server import server
from recon.pipeline import load_raw


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    """Point every file path at a throwaway folder.

    tmp_path is a fresh empty folder pytest creates for each test. monkeypatch
    swaps our settings for a copy that uses it — so tests never touch your
    real data/ folder or DuckDB file, and never interfere with each other.
    """
    temp = dataclasses.replace(
        settings,
        project_root=tmp_path,
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        eval_dir=tmp_path / "eval",
        documents_dir=tmp_path / "raw" / "documents",
        duckdb_path=tmp_path / "processed" / "recon.duckdb",
        proposals_path=tmp_path / "processed" / "proposals.jsonl",
    )
    # Each module did `from recon.config import settings`, which gives it its
    # OWN name for the object — so we have to patch that name in each module.
    for module in (generate, documents, load_raw, server):
        monkeypatch.setattr(module, "settings", temp)
    return temp
