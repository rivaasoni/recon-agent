# 2-minute demo video: script and shot list

Two minutes is about 300 spoken words. Everything below is timed for that.

**Don't run anything live.** The agent takes about 32 seconds per case, and dead air
ruins a demo. Run it all first, then talk over results that already exist.

---

## Before you record

- [ ] `python -m recon.pipeline.run`
- [ ] `python -m recon.agent.run_all --max-cost 6`
- [ ] `python -m recon.evals.report`
- [ ] `python -m recon.pipeline.refresh_analytics`
- [ ] Approve 2 or 3 cases in the Streamlit app so the review screen isn't empty
- [ ] Close anything showing `.env`, your API key, or your billing page
- [ ] Terminal font at 18 to 20pt. Small text is unreadable once the video is compressed
- [ ] Browser zoom around 125%, bookmarks hidden, other tabs closed
- [ ] Have these open: terminal, the architecture diagram on GitHub, the Streamlit app, the eval report
- [ ] Record at 1080p (QuickTime: File, then New Screen Recording)

---

## The script

### 0:00 to 0:15 : the problem

**On screen:** the two CSV files side by side, or the exceptions table in the terminal.

"Every month, finance teams compare their bank statement to their own records. Most
lines match. The leftovers are called exceptions, and each one gets investigated by
hand. Is this a duplicate payment, a bank fee nobody wrote down, or money that just
hasn't arrived yet? That's days of work a month."

### 0:15 to 0:30 : what I built

**On screen:** the architecture diagram on GitHub.

"I built an agent that investigates those exceptions. Plain rules clear the easy matches
first, 114 of 125 lines here. Only the 16 real exceptions reach the agent, which looks
things up and suggests a fix. It can't post anything. A person approves every suggestion."

### 0:30 to 1:05 : the agent working

**On screen:** `python -m recon.agent.show_trace CASE-006`, scrolling slowly.

"Here's one case. The agent reads the exception, then pulls the bank row, the ledger row
and the supporting documents at the same time. The supplier's bill says 9,400 pounds.
The bank's wire confirmation says it converted at 1.3022, but the ledger used 1.2800.
That's the whole difference: $208.68, caused by the exchange rate, not by a mistake.

It suggests an entry, lists the four documents it used, and stops. Every step is saved,
including what it cost, so you can check the reasoning later."

### 1:05 to 1:35 : the person decides

**On screen:** the Streamlit app. Open a timing difference case (CASE-013, 015 or 016).
Expand the reasoning, then click Approve.

"The reviewer sees the case, the suggested entry, the evidence and the full reasoning
before deciding. This one's my favourite: the agent suggested doing nothing. The payment
was recorded on the 31st and reaches the bank in September, so the right answer is to
wait. Knowing when not to act matters as much as suggesting a fix.

Approving records who decided and when, and still posts nothing. Approved entries come
out as a CSV for a person to import."

### 1:35 to 1:55 : does it actually work?

**On screen:** the eval report, headline numbers then the confusion matrix.

"I generate the data with an answer key the agent never sees, and score every run
against it. Both the type of problem and whether the suggested entry moves the money by
the right amount, down to the cent. This run got 16 out of 16 on both, for $1.69, about
ten cents a case.

That's 16 made-up cases with clean evidence, so the report lists the caveats underneath.
Next I'd test harder cases: partial payments, batched deposits, missing paperwork."

### 1:55 to 2:00 : close

**On screen:** the README results table.

"Python, DuckDB, dbt, a tool server and Claude, with 188 tests, including a fake model
that runs the whole agent loop for free. Code's in the repo."

---

## Shot list

| Time | Screen | What to do |
|---|---|---|
| 0:00 | Terminal | The exceptions table, 16 rows |
| 0:15 | GitHub | The architecture diagram |
| 0:30 | Terminal | `show_trace CASE-006`, scroll slowly |
| 1:05 | Browser | Streamlit: a timing case, reasoning expanded, click Approve |
| 1:35 | GitHub | The eval report: headline, then the confusion matrix |
| 1:55 | GitHub | The README results table |

---

## Tips

- Record in three takes, not one. Problem and architecture, then the demo, then results. Cut them together.
- Move the mouse slowly. Fast pointer movement is hard to watch.
- Pause for a second before clicking so viewers see where you're going.
- Say numbers the way they're written: "ninety-one percent", "one dollar sixty-nine".
- Don't apologise on camera. No "this is only a small project".
- Add captions if you post it. Most people watch without sound.

## The 30-second version, for interviews

When someone asks you to talk about a project:

> "I built an agent that sorts out bank reconciliation exceptions. Rules match 91% of
> the bank lines automatically, so only the real problems reach the model. It looks
> things up and suggests a correcting entry, and it physically can't post anything
> because I never gave it a tool that could. A person approves each one with the
> reasoning in front of them. I score every run against an answer key the agent can't
> see: 16 out of 16 on both the type and the entry, at about ten cents a case. It's a
> small made-up dataset though, so I'd want to test partial payments and batched
> deposits next, which is where I'd expect it to struggle."
