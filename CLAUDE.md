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
| UI | **Streamlit** | Human-in-the-loop approve/reject. |
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
- [ ] **Phase 2 — Synthetic data generator.** One month of bank statement + general ledger, with seeded exceptions of known types. Also writes an **answer key** listing each seeded exception and its correct classification.
- [ ] **Phase 3 — Data pipeline.** Load raw files into DuckDB; dbt staging + cleaned models; dbt tests (not_null, unique, accepted_values).
- [ ] **Phase 4 — Rule-based matching.** Match on amount, date window, and reference. Outputs a matched table and an exceptions table.
- [ ] **Phase 5 — Agent tools as an MCP server.** Tools: (a) query ledger/bank tables, (b) search supporting documents, (c) propose a correcting journal entry (**proposal only, never executed**).
- [ ] **Phase 6 — Agent loop.** Agent works each exception, calls tools, classifies, explains reasoning, drafts a fix. Every step logged as a trace.
- [ ] **Phase 7 — Human-in-the-loop UI.** Streamlit: exception + reasoning trace + Approve / Reject.
- [ ] **Phase 8 — Evaluation harness.** Agent classifications vs. answer key. Accuracy by exception type, confusion matrix, cost and latency per run, failure-case list.
- [ ] **Phase 9 — Analytics layer.** Metrics tables: match rate, exceptions by type, dollar value of open breaks, resolution rate. Power BI ready.
- [ ] **Phase 10 — Polish.** README as a case study (problem, requirements, user stories, architecture diagram, eval results, limitations, next steps) + 2-minute demo video script outline.

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
│   └── processed/      # DuckDB file, outputs  (git-ignored)
├── docs/               # Architecture diagram, case study assets
├── scripts/            # One-off runnable entry points
├── tests/              # pytest
└── pyproject.toml      # pytest config (pythonpath) — see note below
```

## 7. Common commands

```bash
source .venv/bin/activate     # ALWAYS first
pytest                        # run tests
python -c "from recon.config import settings; print(settings)"
```

**Note on imports:** `pyproject.toml` sets `pythonpath = ["."]` under
`[tool.pytest.ini_options]`. Without it, a bare `pytest` fails with
`ModuleNotFoundError: No module named 'recon'` while `python -m pytest`
succeeds — because only the `-m` form adds the current directory to
`sys.path`. Do not remove that setting.
