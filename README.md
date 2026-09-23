# Bank Reconciliation Exceptions Agent

> **Everything here is fake data.** No real bank, company or customer information is
> used. A script in this repo generates all of it.

Every month, accountants compare the bank's records with their company's own records.
Most lines match. The ones that don't are called **exceptions**, and someone has to
work out what happened to each one by hand.

I built a system that does the easy matching with plain rules, then hands the leftovers
to an AI agent. The agent looks things up, works out what kind of problem it is, writes
a suggested fix, and stops there. A person approves or rejects it. Nothing is ever
posted to the company's books automatically.

### ▶ [See the live demo](https://recon-agent-zeta.vercel.app)

All 16 exceptions, what the agent decided, and how it got there. The demo is read-only,
so it doesn't call an AI model or cost anything to visit.

---

## Results

I generated one month of data: 125 bank lines, 125 ledger entries, and 16 problems of
6 known types hidden inside.

| | Result |
|---|---|
| Matched by rules | 114 of 125 bank lines (91%) |
| Left for the agent | 16 exceptions, worth $84,583 |
| Got the right type | 16 out of 16 |
| Got the right fix | 16 out of 16, correct to the cent |
| Cost | $1.69 for the whole run, about 10 cents per case |
| Speed | 32 seconds per case |

[Full report with the confusion matrix and caveats](docs/evals/report-run-20260921-215515.md)

100% on 16 made-up cases doesn't mean the problem is solved. I've written down why in
[Limitations](#limitations).

---

## The problem

A bank statement says what the bank thinks happened. A general ledger says what the
company's accountants recorded. They should agree, and they almost never do.

Most differences are easy: same invoice number, same amount, a day apart. The rest take
real work. Someone has to find the invoice, check the wire confirmation, and decide
whether the difference is a fee nobody wrote down, a payment entered twice, a currency
conversion at a different rate, or money that just hasn't arrived yet.

These are the six types my project covers:

| Type | What happened | What to do |
|---|---|---|
| Timing difference | Recorded at month end, reaches the bank next month | Nothing. It sorts itself out |
| Duplicate | The same bill was entered twice | Reverse the extra one |
| Bank fee | The bank charged a fee nobody recorded | Record the fee |
| FX difference | Booked at one exchange rate, paid at another | Record the gain or loss |
| Missing ledger entry | Money moved but nobody recorded it | Record the transaction |
| Amount mismatch | Someone typed two digits the wrong way round | Correct the amount |

One of the six right answers is "do nothing". That matters. An assistant that tries to
fix a timing difference makes things worse, so I test for that too.

---

## What the users needed

I wrote these as user stories before building anything:

> **As an accountant**, I want the obvious matches cleared automatically, so I only
> spend time on the ones that need thinking about.

> **As an accountant**, I want each exception to come with a suggested answer, a draft
> journal entry and the evidence behind it, so I can approve or reject it quickly.

> **As a controller**, I want to see the agent's reasoning before anything is approved,
> and a record of who approved what, so the process holds up in an audit.

> **As the person who owns the system**, I want to know how accurate the agent is and
> what a run costs, so I can decide where it's safe to use.

Four rules came out of that, and they shaped the whole design:

1. The agent can never write to the books. Not because I told it not to, but because it has no tool that could.
2. Every decision has to be explainable, with the evidence it used.
3. Accuracy has to be measured against a known answer, not guessed at.
4. Cost has to be visible per case, because an agent that costs more than the work it saves isn't worth running.

---

## How it works

```
Fake data  →  Database + dbt  →  Rule matching  →  16 exceptions
                                                        │
                                          Agent looks things up
                                                        │
                                    Suggested fix (marked pending)
                                                        │
                                   Person approves or rejects
                                                        │
                                  CSV for a human to post + scorecard
```

[Full diagram and the design decisions behind it](docs/architecture.md)

| Step | What happens |
|---|---|
| Generate | One month of fake bank and ledger data, 32 supporting documents, and an answer key |
| Load | Files go into DuckDB untouched, then dbt cleans and types them with 80+ data quality tests |
| Match | Same reference, same amount, dates within a few days. One-to-one only |
| Give the agent tools | A small tool server lets it look up rows and search documents, read-only |
| Investigate | The agent works each case and writes down every step it took |
| Review | A Streamlit app shows the case, the suggested entry, the evidence and the reasoning |
| Grade | Compare what the agent said against the answer key |
| Report | Metrics tables for Power BI: match rate, breaks by type, open value, cost |

### One case, start to finish

CASE-006 took the agent 5 steps and 15 cents:

1. Read the case: both sides exist, bill `BILL-5059`, off by $208.68, ledger says GBP
2. Pulled the bank row, the ledger row and the documents at the same time
3. Found the bill (GBP 9,400.31) and the bank's wire confirmation. The bank used rate 1.3022, the ledger used 1.2800
4. Noticed a $35 wire fee in the confirmation, checked it, and found it belonged to a different case
5. Suggested: debit FX Gain/Loss $208.68, credit Cash $208.68

That matches the answer key exactly. It also explained why it wasn't a duplicate or a
typo, and flagged the fee cases for someone to look at.

---

## Limitations

- **The data is fake and tidy.** Every problem has clear evidence somewhere. Real bank
  statements have partial payments, one deposit covering five invoices, missing
  paperwork and cases where two answers are both defensible.
- **16 cases is a small test.** Two or three per type. One wrong answer would drop a
  type from 100% to 50%, so the per-type numbers show where to look, not how often it's right.
- **One run, one month, one model.** AI output varies between runs. I'd need to run it
  several times to say anything about consistency.
- **The matching rule is strict.** It works because my data always has a clean reference
  number. Real data needs fuzzy matching, and a looser rule would risk matching two
  things that don't belong together, which hides problems instead of showing them.
- **Cost doesn't follow value.** The agent spent $0.38 on $115 of bank fees and $0.26 on
  $36,500 of duplicates. It spends based on how much digging a case needs, not how much
  money is at stake.
- **Nothing is posted anywhere.** Approved fixes come out as a CSV for a person to
  import. That's on purpose.

## What I'd do next

1. Harder test cases: partial payments, batched deposits, missing documents, and cases where the answer is genuinely unclear.
2. Send cheap, obvious cases (like fees that match the bank's published fee schedule) to a rule instead of the agent.
3. Run the same test on a cheaper model and compare accuracy against cost.
4. Use the reviewer's rejection notes to improve the prompt.
5. More than one month, and more than one bank account.

---

## Running it yourself

You need Python 3.13. dbt doesn't support 3.14 yet. Everything except the agent runs
without an API key.

```bash
git clone <this-repo-url> && cd recon-agent
python3.13 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # add your Anthropic API key (only needed for the agent)

pytest                          # 188 tests, no API key needed
python -m recon.pipeline.run    # make the data, load it, build and test the models
python -m recon.matching.evaluate   # check the matching against the answer key
```

With an API key (the full run costs about $1.70):

```bash
python -m recon.agent.hello_claude            # check the key works (under 1 cent)
python -m recon.agent.run_case CASE-006       # one case, showing every step (~15 cents)
python -m recon.agent.run_all --max-cost 6    # all 16 cases
python -m recon.evals.report                  # score the run and write the report

streamlit run app/review_app.py               # the approve/reject app (free)
python -m recon.pipeline.refresh_analytics    # rebuild the metrics and export them
```

---

## What I used

| Part | Tool | Why |
|---|---|---|
| Database | DuckDB | A real SQL database that's just a file. Nothing to install or run |
| Data models | dbt | SQL that lives in git, with tests attached |
| The agent | Anthropic SDK Tool Runner, Claude Opus 5 | I can see every step of the loop, which heavier frameworks hide |
| The agent's tools | A small MCP server I wrote | The tools work with any MCP client, and it's where I enforce read-only access |
| Review app | Streamlit | The approve/reject screen, in one Python file. It saves decisions, so it runs locally rather than on a public URL |
| Public demo | Plain HTML, CSS and JS on Vercel | Read-only, no backend, so it can't call the model or cost anything |
| Tests | pytest | 188 tests, including a fake model that runs the whole agent loop for free |
| Dashboards | Power BI | Reads the exported metrics files |

---

## Things that went wrong (and what I changed)

- **Testing the agent was expensive**, so I wrote a fake model that follows a script. The
  tools, database and files stay real. Now I can test tool errors, network failures and
  budget limits in under a second, for nothing.
- **A real network outage killed 3 of 16 cases mid-run.** The other 13 still finished,
  and failed cases cost nothing because nothing completed. I added a `--resume` option,
  which finished the run for 38 cents instead of repeating $1.69.
- **One of my tests could never fail.** I only found out by deliberately breaking the
  thing it was supposed to catch. I now do that with any test that guards something important.
- **My test data fell behind my real data.** The fake database in my tests was missing
  columns the app used, so the UI tests broke. There's now a test comparing them.
- **Duplicates broke my first matching attempt.** One payment with two identical ledger
  entries would match both and hide the duplicate. Matching is now strictly one-to-one,
  oldest first, so the second entry shows up as an exception.
- **The live site 404'd on every reasoning trace.** A line in `.gitignore` was hiding the
  files without telling me. I added a test that checks nothing the site needs is ignored.

---

## License

MIT. See [LICENSE](LICENSE).
