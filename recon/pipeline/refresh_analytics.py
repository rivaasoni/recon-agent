"""
Refresh the analytics layer with one command — Phase 9.

    1. Load the agent's outputs (proposals, decisions, traces) into raw
    2. dbt build  (staging + cleaned + matching + analytics, with all tests)
    3. Export the analytics tables for Power BI

Run this after an agent run, or after reviewing cases in the Streamlit app,
to bring the dashboards up to date.

    python -m recon.pipeline.refresh_analytics
"""

from __future__ import annotations

from recon.pipeline import export_analytics, load_agent_outputs
from recon.pipeline.run import run_dbt_build


def main() -> None:
    print("=== 1/3  Load agent outputs into DuckDB ===")
    load_agent_outputs.main()

    print("\n=== 2/3  dbt build (models + tests) ===", flush=True)
    run_dbt_build()

    print("\n=== 3/3  Export analytics tables ===")
    export_analytics.main()


if __name__ == "__main__":
    main()
