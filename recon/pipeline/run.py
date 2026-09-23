"""
Run the whole data pipeline with one command:

    python -m recon.pipeline.run

It does, in order:
    1. Generate the synthetic data      (recon/data_gen/generate.py)
    2. Load raw files into DuckDB       (recon/pipeline/load_raw.py)
    3. Load agent outputs               (recon/pipeline/load_agent_outputs.py)
    4. dbt build: every model, then all data tests

Each step only runs if the previous one succeeded.

Step 3 looks odd on a fresh clone — the agent hasn't run, so there is nothing
to load. It still has to happen: the Phase 9 models read raw.agent_*, and
those tables must EXIST (even with no rows) or dbt fails. The loader creates
empty tables when there are no files.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from recon.config import settings
from recon.data_gen import generate
from recon.pipeline import load_agent_outputs, load_raw

DBT_PROJECT_DIR = settings.project_root / "dbt_recon"


def run_dbt_build() -> None:
    """Run `dbt build` from inside the dbt project folder.

    We call the dbt that sits next to this Python (in .venv/bin/), so it works
    even if you forgot to activate the virtual environment.
    """
    dbt = Path(sys.executable).parent / "dbt"
    # cwd= runs the command from dbt_recon/, where profiles.yml lives.
    # dbt prints its own output straight to your terminal.
    result = subprocess.run([str(dbt), "build"], cwd=DBT_PROJECT_DIR)
    if result.returncode != 0:
        # A non-zero return code means dbt failed. Stop here, loudly.
        sys.exit("\ndbt build FAILED — scroll up to see which model or test failed.")


def main() -> None:
    print("=== 1/4  Generate synthetic data ===")
    generate.main()

    print("\n=== 2/4  Load raw files into DuckDB ===")
    load_raw.main()

    # Empty on a fresh clone — but the tables must exist for dbt. See above.
    print("\n=== 3/4  Load agent outputs (empty until the agent has run) ===")
    load_agent_outputs.main()

    # flush=True pushes everything printed so far out NOW. Otherwise Python may
    # still be holding it in a buffer when dbt (a separate program) starts
    # writing, and dbt's output would appear before ours.
    print("\n=== 4/4  dbt build (models + tests) ===", flush=True)
    run_dbt_build()

    print("\nPipeline finished. Cleaned tables are ready in the `cleaned` schema.")


if __name__ == "__main__":
    main()
