# 2-minute demo video — script and shot list

Two minutes is roughly **300 spoken words**. Everything below is timed for that.

**The golden rule: nothing runs live.** The agent takes ~32 seconds per case; dead
air ruins a demo. Run everything first, then narrate over results that already exist.

---

## Before you record

- [ ] `python -m recon.pipeline.run` — data, warehouse, matching all fresh
- [ ] `python -m recon.agent.run_all --max-cost 6` — a complete run of all 16 cases
- [ ] `python -m recon.evals.report` — the eval report exists
- [ ] `python -m recon.pipeline.refresh_analytics` — metrics exported
- [ ] Approve 2–3 cases in the Streamlit app, so the review screen isn't empty
- [ ] **Close anything showing `.env`, your API key, or the Console billing page**
- [ ] Terminal font at ~18–20pt; a small font is unreadable when compressed
- [ ] Browser zoom ~125% for Streamlit; hide bookmarks and other tabs
- [ ] Have these open and ready: terminal, `docs/architecture.md` on GitHub,
      the Streamlit app, `report.md`
- [ ] Record at 1080p. Mac: QuickTime (File → New Screen Recording) or Loom

---

## The script

### 0:00–0:15 — The problem

> **On screen:** the two CSVs side by side, or the exceptions table in the terminal.

"Every month, finance teams compare their bank statement to their ledger. Most lines
match automatically. The leftovers are called exceptions, and each one has to be
investigated by hand — is this a duplicate payment, a bank fee nobody booked, or just
money still in transit? That's days of work a month."

### 0:15–0:30 — What I built

> **On screen:** `docs/architecture.md` on GitHub, the diagram visible.

"I built an agent that investigates those exceptions. Deterministic rules clear the
easy matches first — 114 of 125 lines here. Only the 16 real exceptions reach the
agent, which uses tools to investigate, then proposes a fix. It can't post anything;
a human approves every proposal."

### 0:30–1:05 — The agent working

> **On screen:** `python -m recon.agent.show_trace CASE-006`, scrolling slowly.

"Here's one case. The agent pulls the exception, then fetches the bank row, the ledger
row and the supporting documents in parallel. The vendor bill says GBP 9,400.31. The
bank's wire confirmation says it converted at 1.3022 — but the ledger used 1.2800.
That's the entire difference: $208.68, a currency-rate difference, not a mistake.

It proposes debit FX Gain/Loss, credit Cash, cites the four documents it relied on, and
stops. Every step is logged — tools, tokens, cost — so the reasoning is auditable."

### 1:05–1:35 — The human decides

> **On screen:** the Streamlit app. Open a **timing_difference** case (CASE-013,
> 015 or 016). Show the trace expander, then click **Approve**.

"The reviewer sees the case, the proposed entry, the evidence and the full reasoning
before deciding. This one is my favourite: the agent proposed **no entry at all**. The
payment was booked on the 31st and clears the bank in September, so the right answer is
to wait. Knowing when not to act matters as much as proposing a fix.

Approving records who decided and when, in an append-only log — and still posts nothing.
Approved entries export as a CSV for a person to import."

### 1:35–1:55 — Does it actually work?

> **On screen:** `docs/evals/report-run-20260921-215515.md`, headline table then the
> confusion matrix.

"I generate the data with a known answer key the agent can never see, and grade every
run against it — the classification *and* the proposed entry's effect on cash, to the
cent. This run: 16 out of 16 on both, for $1.69, about ten cents a case.

That's 16 synthetic cases with clean evidence, so the report lists the caveats under the
headline. My next step is harder cases: partial payments, batched deposits, missing
paperwork."

### 1:55–2:00 — Close

> **On screen:** the README results table.

"Python, DuckDB, dbt, an MCP server and Claude, with 177 tests — including a fake model
that exercises the whole agent loop for nothing. Code's in the repo."

---

## Shot list

| Time | Screen | Action |
|---|---|---|
| 0:00 | Terminal | The exceptions table (16 rows) |
| 0:15 | GitHub | `docs/architecture.md` diagram |
| 0:30 | Terminal | `show_trace CASE-006`, scroll slowly |
| 1:05 | Browser | Streamlit: a timing case, trace expanded, click Approve |
| 1:35 | VS Code/GitHub | The eval report: headline, then confusion matrix |
| 1:55 | GitHub | README results table |

---

## Tips

- **Record in 3 takes, not 1.** Problem + architecture, demo, results. Cut them together.
- **Move the mouse slowly and deliberately.** Fast pointer movement is unwatchable.
- **Pause 1 second before clicking**, so the viewer sees where you're about to click.
- **Say numbers exactly as written.** "Ninety-one point two percent", "one dollar sixty-nine".
- **Don't apologise on camera.** No "this is just a small project". Describe what it does.
- **Subtitle or caption the video** if you post it — most people watch muted.

## The 30-second version (for interviews)

When someone asks "tell me about a project", this is the spoken form:

> "I built an agent that resolves bank reconciliation exceptions. Rules match 91% of
> bank lines automatically, and only the genuine exceptions reach the model, which
> investigates with tools and proposes a correcting journal entry — it physically can't
> post anything, because no tool exists to. A human approves each one with the full
> reasoning in front of them. I grade every run against a ground-truth answer key the
> agent can't see: 16 out of 16 on both the classification and the entry, at about ten
> cents a case. It's a small synthetic set, so I'd next test partial payments and
> batched deposits, which is where I'd expect it to struggle."
