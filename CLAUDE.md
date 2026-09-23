# CLAUDE.md — Agentic Reconciliation Exceptions Assistant

This file is read automatically at the start of every session. It captures how the
owner of this repo wants to work and what we are building, so context is not lost
between sessions.

---

## 1. Who I'm working with, and how

The owner is an **early-career data/AI analyst** building this as a **portfolio
project** to land roles in **AI engineering, data engineering, and data analytics**.
They are still learning.

**Act as a patient senior engineer and mentor, not a code generator.**

Non-negotiable working agreement:

| Rule | What it means in practice |
|---|---|
| **One phase at a time** | Do NOT start the next phase until the user literally says "next phase." |
| **Explain before coding** | Before each step, 2–4 plain-language sentences: what we're building and why. |
| **Small steps** | After each step, state the exact command to run, what they should see, and how to verify it worked. |
| **Teach new concepts** | When introducing a concept (dbt model, MCP server, eval harness, ...), give a short explanation AND one question they should be able to answer afterward. |
| **Debug together** | On an error, help them *read and understand* the error message before fixing it. |
| **End-of-phase wrap-up** | Every phase ends with: (a) what they learned, (b) a suggested git commit message, (c) 2–3 interview talking points. |
| **Code style** | Clean, commented, beginner-readable. **Prefer simple over clever.** No premature abstraction. |

---

## 2. Hard guardrails

- **All data is SYNTHETIC.** Never use, invent-as-if-real, or reference real company,
  bank, customer, or account data. Generated data must be obviously fake.
- **The agent never writes.** It *proposes* correcting journal entries. A human
  approves before anything is committed. This is the core design premise, not a nicety.
- **Secrets never leave the machine.** `.env` holds the API key and is git-ignored.
  `.env.example` (no real values) is committed.
- **Generated data is not committed.** `data/` contents are git-ignored; folders are
  kept via `.gitkeep`.

---

## 3. Project summary

An AI agent that helps resolve **bank reconciliation exceptions**.

Rule-based matching handles the easy matches between a bank statement and a general
ledger. Whatever is left over — the *exceptions* — is handed to an agent, which
investigates using tools, classifies the exception, drafts a proposed fix, and then
**waits for human approval** before anything is written.

**Exception types in scope:** timing differences, duplicates, bank fees, FX
differences, missing ledger entries, amount mismatches.

---

## 4. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | **Python 3.13** (Anaconda) | `/opt/anaconda3/bin/python3.13`. System default is 3.14, which is too new for dbt — do not use it. |
| Env | `venv` at `.venv/` | Always activate before running anything. |
| Warehouse | **DuckDB** | Local file at `data/processed/recon.duckdb`. |
| Transforms | **dbt-duckdb** | Staging + cleaned models, plus data quality tests. |
| Agent | **Anthropic SDK Tool Runner** | `client.beta.messages.tool_runner`. Chosen over LangChain/CrewAI so the agent loop stays visible and explainable in interviews. |
| Model | `claude-opus-5` | Default. Use adaptive thinking. Cheaper swap: `claude-sonnet-5`. |
| Tools | **Custom MCP server** (`mcp` package) | Exposes the agent's tools over a standard protocol. |
| Review UI | **Streamlit** | Human-in-the-loop approve/reject. Writes decisions, so it runs locally — NOT deployable to Vercel (Streamlit needs a long-lived server). |
| Public demo | **Static HTML/CSS/JS in `web/`, hosted on Vercel** | Read-only view of pre-computed results. No backend, no API key, no model calls. Data exported by `python -m recon.pipeline.build_web_demo`. |
| Tests | **pytest** | |
| BI | Power BI | Connects to the analytics layer in Phase 9. |

### Anthropic API conventions for this repo
- Model ID is exactly `claude-opus-5` — never append a date suffix.
- Use `thinking={"type": "adaptive"}`. Do **not** use `budget_tokens` (rejected with a 400 on this model).
- No assistant prefill — it returns a 400.
- Stream any request with large `max_tokens`.
- Before writing Claude API code, load the `claude-api` skill rather than working from memory.

---

## 5. Phase plan

Phases are strictly sequential. Current status is tracked in the checkboxes below —
**update them as phases complete.**

- [x] **Phase 1 — Project setup.** Folder structure, venv, requirements, `.gitignore`, README skeleton, git init, first GitHub push.
- [x] **Phase 2 — Synthetic data generator.** One month of bank statement + general ledger, with seeded exceptions of known types. Also writes an **answer key** listing each seeded exception and its correct classification. Built: `python -m recon.data_gen.generate` → `data/raw/*.csv`, `data/raw/documents/DOC-*.txt` (supporting evidence + noise, never labels), `data/eval/answer_key.csv` (16 exceptions, self-balancing check).
- [x] **Phase 3 — Data pipeline.** Load raw files into DuckDB; dbt staging + cleaned models; dbt tests (not_null, unique, accepted_values). Built: `raw` schema (all VARCHAR + lineage cols, loaded by `recon/pipeline/load_raw.py`) → `staging` views → `cleaned` tables (`bank_transactions`, `gl_entries`, `documents`). `unique` on `gl_entries.reference` is severity **warn** on purpose — it flags the seeded duplicates (business exceptions, not pipeline errors). Later phases read ONLY from `cleaned`.
- [x] **Phase 4 — Rule-based matching.** Match on amount, date window, and reference. Outputs a matched table and an exceptions table. Built as dbt models in the `matching` schema: `match_rule1_exact` (ref + amount + ±`match_date_window_days`, one-to-one, FIFO so the later duplicate posting is left over) and `exceptions` (one row per CASE: `both_sides` / `bank_only` / `ledger_only`, facts only — never a classification). A looser fallback rule was deliberately NOT built: every leftover is a real exception, so it could only create false matches. `python -m recon.matching.evaluate` scores it vs `data/eval/true_matches.csv` + answer key (currently 100% / 100%, 16/16 caught — expected on clean synthetic data).
- [x] **Phase 5 — Agent tools as an MCP server.** Tools: (a) query ledger/bank tables, (b) search supporting documents, (c) propose a correcting journal entry (**proposal only, never executed**). Built in `recon/mcp_server/server.py`: 7 read-only tools (cases, bank/ledger rows with match status, reference lookup, document lookup/search) + `propose_journal_entry` (validates double entry with Decimal, appends to `settings.proposals_path` as `pending_human_approval`; never touches the warehouse). Tool list is locked by a test. Uses **mcp 2.x**: `from mcp.server.mcpserver import MCPServer` (NOT `FastMCP` — renamed in 2.x); errors via `ToolError`; tests use in-memory `mcp.Client(server)` + `@pytest.mark.anyio`. Phase 6 connects via `stdio_client` + `ClientSession` and `anthropic.lib.tools.mcp.async_mcp_tool` (see `recon/mcp_server/stdio_check.py`).
- [x] **Phase 6 — Agent loop.** Agent works each exception, calls tools, classifies, explains reasoning, drafts a fix. Every step logged as a trace. Built: `recon/agent/loop.py` (Tool Runner + MCP over stdio; adaptive thinking with `display: "summarized"`; prompt caching; `max_iterations=15`; trace written even on failure, with status `completed` / `no_proposal` / `hit_iteration_cap` / `refused` / `error`), `run_all.py` (batch with error isolation, per-case retries, `--max-cost` budget cap, `--resume <run_id>`), `show_trace.py` (readable trace viewer), `prompts.py` (system prompt: goal + rules + label definitions, deliberately NO per-type recipes). Traces: `data/processed/traces/<run_id>/<CASE>.json` + `_summary.json`. **Tests use a scripted fake Claude — the whole loop is tested with no API cost.** First full run: 16/16 completed, $1.69, ~38s/case.
- [x] **Phase 7 — Human-in-the-loop UI.** Streamlit: exception + reasoning trace + Approve / Reject. Built: `recon/review/store.py` (merges cases + proposals + traces + decisions; append-only `decisions.jsonl`; `approved_entries`/`entries_csv` export; `review_metrics`) and `app/review_app.py` (`streamlit run app/review_app.py`). Rules: a decision must name a reviewer, rejecting requires a note, deciding again appends (latest wins, history kept), approving posts NOTHING — the CSV is a hand-off for a human to post. UI tested headlessly with `streamlit.testing.v1.AppTest`; all review logic lives in the store so it is testable without the UI.
- [x] **Phase 8 — Evaluation harness.** Agent classifications vs. answer key. Accuracy by exception type, confusion matrix, cost and latency per run, failure-case list. Built: `recon/evals/grade.py` (joins CASE-ids to EXC-ids via shared bank/ledger row IDs — the two ID spaces are deliberately unrelated; grades **classification** AND the **fix** by comparing net cash effect to the cent; offset account is a soft signal only) and `recon/evals/report.py` → `data/eval/reports/<run_id>/` (report.md, results.csv, failures.csv, confusion_matrix.csv, metrics.json). Report always carries its caveats. **First result (run-20260921-215515, claude-opus-5): 16/16 classification, 16/16 fix, $1.69, $0.106/case, 32s median.**
- [x] **Phase 9 — Analytics layer.** Metrics tables: match rate, exceptions by type, dollar value of open breaks, resolution rate. Power BI ready. Built: `recon/pipeline/load_agent_outputs.py` (proposals/decisions/traces → `raw.agent_*`; empty frames are cast to string or DuckDB guesses INTEGER), staging models for them (surrogate key `run_id:case_id`), `analytics.fct_exception_cases` (one row per case; latest proposal, decision joined **via proposal_id**, latest run) and 4 metrics marts. `recon/pipeline/refresh_analytics.py` = load → dbt build → export to `data/processed/analytics/*.{parquet,csv}` for Power BI. **Ground truth (`data/eval/`) still never enters the warehouse** — accuracy lives in the Phase 8 report, operational metrics here. First numbers: 91.2% bank lines matched (95.7% by value), 16 breaks worth $84,583.56, 40% of that value self-clearing (timing).
- [x] **Phase 10 — Polish.** README as a case study (problem, requirements, user stories, architecture diagram, eval results, limitations, next steps) + 2-minute demo video script outline. Built: `README.md` (case study), `docs/architecture.md` (Mermaid diagram + trust boundaries), `docs/demo-script.md` (2-min script + 30-sec interview version), `docs/evals/` (promoted eval report), `LICENSE` (MIT). A **fresh-clone check** caught a real bug — `pipeline.run` now loads agent outputs before `dbt build`, so the Phase 9 models don't fail on a machine where the agent never ran.

- [x] **Bonus — Public demo.** Static read-only site in `web/` (plain HTML/CSS/JS, no build step), data exported by `python -m recon.pipeline.build_web_demo` into `web/data/` (**committed on purpose** — Vercel serves the repo). Deployed at **https://recon-agent-zeta.vercel.app** via GitHub import with Root Directory = `web`; every push redeploys. Never calls the API. Gotcha fixed: `.gitignore` patterns **without a slash match at any depth**, so `traces/` silently ignored `web/data/traces/` and 404'd the live site — now `/traces/`, with a test.

**ALL 10 PHASES COMPLETE.** 188 tests, 83 dbt models+tests, live demo at https://recon-agent-zeta.vercel.app. Remaining optional work is listed in the README's "Next steps": harder eval cases, routing by value, a cheaper-model comparison, learning from rejection notes, multi-month data.

---

## 6. Repo layout

```
.
├── recon/              # The Python package (top-level, so no packaging setup needed)
│   ├── config.py       # Paths + settings, loaded from .env
│   ├── data_gen/       # Phase 2
│   ├── pipeline/       # Phase 3
│   ├── matching/       # Phase 4
│   ├── mcp_server/     # Phase 5
│   ├── agent/          # Phase 6
│   └── evals/          # Phase 8
├── dbt_recon/          # dbt project (Phase 3)
├── app/                # Streamlit app (Phase 7)
├── data/
│   ├── raw/            # Generated CSVs        (git-ignored)
│   ├── processed/      # DuckDB file, outputs  (git-ignored)
│   └── eval/           # Answer key — agent must NEVER see this (git-ignored)
├── docs/               # Architecture diagram, case study assets
├── scripts/            # One-off runnable entry points
├── tests/              # pytest
└── pyproject.toml      # pytest config (pythonpath) — see note below
```

## 7. Common commands

```bash
source .venv/bin/activate     # ALWAYS first
pytest                        # run tests
python -m recon.pipeline.run  # generate data -> load DuckDB -> dbt build (all of Phases 2–3)
cd dbt_recon && dbt build     # dbt only — must run from inside dbt_recon/ (profiles.yml lives there)
python -m recon.matching.evaluate   # score the matcher against ground truth (run after the pipeline)
python -m recon.mcp_server.call_tool                                   # list MCP tools
python -m recon.mcp_server.call_tool get_exception_case case_id=CASE-005   # call one tool
python -m recon.mcp_server.stdio_check  # connect to the server as a real subprocess (no API cost)

# Phase 6 — these COST MONEY (~$0.10-0.15 per case on Opus 5):
python -m recon.agent.hello_claude               # check the API key works (<$0.01)
python -m recon.agent.run_case CASE-006          # one case, printing every step
python -m recon.agent.run_all --max-cost 6       # all 16 cases (~$1.70)
python -m recon.agent.run_all --resume RUN_ID    # finish an interrupted run (only unfinished cases)
python -m recon.agent.show_trace CASE-006        # read a saved trace (free)

streamlit run app/review_app.py   # Phase 7 review UI (free) — Ctrl+C to stop
python -m recon.evals.report      # Phase 8: grade the latest run + write the report (free)
python -m recon.pipeline.refresh_analytics   # Phase 9: load agent outputs -> dbt build -> export for Power BI
python -c "from recon.config import settings; print(settings)"
```

**Note on imports:** `pyproject.toml` sets `pythonpath = ["."]` under
`[tool.pytest.ini_options]`. Without it, a bare `pytest` fails with
`ModuleNotFoundError: No module named 'recon'` while `python -m pytest`
succeeds — because only the `-m` form adds the current directory to
`sys.path`. Do not remove that setting.
