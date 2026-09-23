"""
Write the evaluation report — Phase 8, Step 4.

Turns a graded run into files you can share:

    data/eval/reports/<run_id>/report.md            for humans
    data/eval/reports/<run_id>/results.csv          one row per case
    data/eval/reports/<run_id>/failures.csv         the cases to fix
    data/eval/reports/<run_id>/confusion_matrix.csv
    data/eval/reports/<run_id>/metrics.json         headline numbers

The report always carries its caveats: a score means nothing without knowing
what it was measured on.

Run it (free — reads saved traces, calls no API):
    python -m recon.evals.report              # the latest run
    python -m recon.evals.report run-20260921-215515
"""

from __future__ import annotations

import json
import sys

import pandas as pd

from recon.agent.costs import PRICES_PER_MILLION  # noqa: F401  (documents pricing source)
from recon.config import settings
from recon.evals.grade import (
    accuracy,
    accuracy_by_type,
    confusion_matrix,
    failure_cases,
    fully_correct,
    grade_run,
)


def headline_metrics(run_id: str, results: pd.DataFrame) -> dict:
    """The numbers that go at the top of the report (and into metrics.json)."""
    costs, times = results["cost_usd"], results["latency_seconds"]
    return {
        "run_id": run_id,
        "cases": len(results),
        "classification_accuracy": round(float(accuracy(results)), 4),
        "fix_accuracy": round(float(accuracy(results, "fix_correct")), 4),
        "fully_correct": round(float(fully_correct(results)), 4),
        "completed_runs": int((results["run_status"] == "completed").sum()),
        "total_cost_usd": round(float(costs.sum()), 4),
        "cost_per_case_usd": round(float(costs.mean()), 4),
        "max_case_cost_usd": round(float(costs.max()), 4),
        "total_seconds": round(float(times.sum()), 1),
        "median_seconds_per_case": round(float(times.median()), 1),
        "total_tool_calls": int(results["tool_calls"].sum()),
        "mean_steps": round(float(results["steps"].mean()), 1),
    }


def markdown_report(metrics: dict, results: pd.DataFrame) -> str:
    """The human-readable report."""
    failures = failure_cases(results)
    by_type = accuracy_by_type(results).rename(
        columns={"expected_type": "Exception type", "correct": "Correct",
                 "total": "Cases", "accuracy": "Accuracy"})
    by_type["Accuracy"] = by_type["Accuracy"].map("{:.0%}".format)

    lines = [
        f"# Agent evaluation — {metrics['run_id']}",
        "",
        "Agent classifications and proposed journal entries, scored against the "
        "answer key generated with the synthetic data.",
        "",
        "## Headline",
        "",
        f"| Metric | Result |",
        f"|---|---|",
        f"| Cases | {metrics['cases']} |",
        f"| Classification accuracy | **{metrics['classification_accuracy']:.0%}** |",
        f"| Fix (entry) accuracy | **{metrics['fix_accuracy']:.0%}** |",
        f"| Fully correct (label **and** entry) | **{metrics['fully_correct']:.0%}** |",
        f"| Runs completed without error | {metrics['completed_runs']}/{metrics['cases']} |",
        f"| Total cost | ${metrics['total_cost_usd']:.2f} |",
        f"| Cost per case | ${metrics['cost_per_case_usd']:.3f} (max ${metrics['max_case_cost_usd']:.3f}) |",
        f"| Median time per case | {metrics['median_seconds_per_case']:.0f}s |",
        f"| Tool calls | {metrics['total_tool_calls']} ({metrics['mean_steps']:.1f} steps per case on average) |",
        "",
        "**Classification accuracy** is the exception type. **Fix accuracy** compares the "
        "proposed entry's net effect on cash with the answer key, to the cent — a correct "
        "label with a wrong amount counts as a failure.",
        "",
        "## Accuracy by exception type",
        "",
        by_type.to_markdown(index=False),
        "",
        "## Confusion matrix",
        "",
        "Rows are the true type, columns what the agent said. Correct answers sit on the "
        "diagonal; a `(none)` column means the agent produced no answer at all.",
        "",
        confusion_matrix(results).to_markdown(),
        "",
        "## Failure cases",
        "",
    ]

    if len(failures):
        lines.append(f"{len(failures)} case(s) were not fully correct.")
        lines.append("")
        for failure in failures.to_dict("records"):
            lines += [
                f"### {failure['case_id']} ({failure['exception_id']}) — {failure['failure_kind']}",
                "",
                f"- **Expected:** {failure['expected_type']}, cash {failure['expected_cash_adjustment']}",
                f"- **Agent said:** {failure['predicted_type']}, cash {failure['proposed_cash_effect']}",
                f"- **Why it failed:** {failure['fix_note']}",
                f"- **Evidence cited:** {failure['evidence'] or '—'}",
                "",
                "<details><summary>The agent's explanation</summary>",
                "",
                str(failure["explanation"] or "(none)"),
                "",
                "</details>",
                "",
            ]
    else:
        lines += ["None — every case was classified correctly and proposed the correct entry.", ""]

    lines += [
        "## How to read this",
        "",
        "- **Sample size.** 16 cases, 2–3 per exception type. One mistake moves a type's "
        "accuracy by 33–50%, so per-type numbers point at what to investigate; they are not "
        "reliable rates.",
        "- **One run.** LLM output varies between runs. Measuring stability needs repeat runs.",
        "- **Synthetic, clean data.** Every exception has decisive evidence reachable through "
        "the tools. Real bank data brings partial payments, batched deposits, missing paperwork "
        "and genuinely ambiguous cases — none of which are represented here.",
        "- **The rules did the easy work first.** Deterministic matching paired 114 of 125 bank "
        "lines, so the agent only saw genuine exceptions.",
        "- **Cost and latency** come from the agent's own traces (tokens × list price).",
        "",
        "Generated by `python -m recon.evals.report`.",
        "",
    ]
    return "\n".join(lines)


def write_report(run_id: str | None = None) -> tuple[str, dict]:
    """Grade a run and write every report file. Returns (folder, metrics)."""
    run_id, results = grade_run(run_id)
    metrics = headline_metrics(run_id, results)

    folder = settings.eval_dir / "reports" / run_id
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "report.md").write_text(markdown_report(metrics, results))
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2))
    results.to_csv(folder / "results.csv", index=False)
    failure_cases(results).to_csv(folder / "failures.csv", index=False)
    confusion_matrix(results).to_csv(folder / "confusion_matrix.csv")
    return str(folder), metrics


def main(args: list[str]) -> None:
    folder, metrics = write_report(args[0] if args else None)
    print(f"Run {metrics['run_id']}: {metrics['cases']} cases")
    print(f"  classification {metrics['classification_accuracy']:.0%} | "
          f"fix {metrics['fix_accuracy']:.0%} | fully correct {metrics['fully_correct']:.0%}")
    print(f"  ${metrics['total_cost_usd']:.2f} total, "
          f"${metrics['cost_per_case_usd']:.3f}/case, "
          f"{metrics['median_seconds_per_case']:.0f}s median")
    print(f"Report written to {folder}")


if __name__ == "__main__":
    main(sys.argv[1:])
