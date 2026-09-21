"""
Central configuration for the reconciliation project.

Why this file exists
--------------------
Every later phase needs to know two kinds of things: *where files live* and
*what settings to use*. If each script hardcodes its own "data/raw/bank.csv",
then moving a folder means hunting through the whole codebase. Instead, every
module imports `settings` from here, and there is exactly one place to change.

Usage:
    from recon.config import settings
    print(settings.raw_dir)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Read key=value pairs from the .env file into the process environment.
# If .env does not exist this quietly does nothing, which is what we want:
# tests and the data generator should run fine without an API key.
load_dotenv()

# PROJECT_ROOT is this file's folder, then up one level (recon/ -> repo root).
# Deriving it from __file__ means the project works no matter which directory
# you happen to run a command from.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """All project settings in one immutable object.

    `frozen=True` means you cannot accidentally reassign a setting at runtime,
    which makes behaviour easier to reason about.
    """

    # --- Filesystem paths --------------------------------------------------
    project_root: Path = PROJECT_ROOT
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    processed_dir: Path = PROJECT_ROOT / "data" / "processed"
    # Supporting documents (invoices, wire confirmations, ...) the agent can search.
    documents_dir: Path = PROJECT_ROOT / "data" / "raw" / "documents"
    # Ground truth for grading the agent (Phase 8). Kept in its own folder so
    # it is never loaded into the warehouse the agent can query.
    eval_dir: Path = PROJECT_ROOT / "data" / "eval"
    docs_dir: Path = PROJECT_ROOT / "docs"

    # The DuckDB warehouse is a single file. Phase 3 creates it.
    duckdb_path: Path = PROJECT_ROOT / "data" / "processed" / "recon.duckdb"

    # --- Model settings ----------------------------------------------------
    # Read from .env so you can switch models without editing code.
    model: str = field(default_factory=lambda: os.getenv("RECON_MODEL", "claude-opus-5"))

    # --- Reproducibility ---------------------------------------------------
    # A fixed random seed means the synthetic data generator produces the SAME
    # data every time. That is essential: the evaluation harness in Phase 8
    # compares agent output against an answer key, and that only means anything
    # if the underlying data does not shift between runs.
    random_seed: int = 42

    def anthropic_api_key(self) -> str:
        """Return the API key, or raise a message that says how to fix it.

        This is a method rather than a field so that merely importing settings
        never fails. You only need a key when you actually call the model.
        """
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key or key.startswith("sk-ant-REPLACE_ME"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set.\n"
                "Fix: copy .env.example to .env and paste your real key:\n"
                "    cp .env.example .env\n"
                "Get a key at https://console.anthropic.com/settings/keys"
            )
        return key

    def ensure_dirs(self) -> None:
        """Create the data folders if they are missing.

        Safe to call repeatedly — `exist_ok=True` means "do nothing if already
        there" rather than raising an error.
        """
        for path in (self.raw_dir, self.processed_dir, self.eval_dir, self.documents_dir):
            path.mkdir(parents=True, exist_ok=True)


# The single shared instance that the rest of the project imports.
settings = Settings()
