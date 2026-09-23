/* ---------------------------------------------------------------------------
   Reconciliation demo — behaviour.

   The whole site is static: it fetches pre-computed JSON from data/ and
   renders it. There is no backend, no database and no AI model call.

   Note: browsers block fetch() on file:// pages, so opening index.html by
   double-clicking shows an empty page. Serve it instead:
       cd web && python -m http.server 8000
   --------------------------------------------------------------------------- */

const state = { summary: null, cases: [], selectedCase: null, traces: {} };

// --- Formatting -------------------------------------------------------------

const money = (value) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });

const percent = (value, digits = 1) =>
  value === null || value === undefined ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;

// 'fx_difference' -> 'FX difference'
const typeLabel = (value) => {
  if (!value) return "unclassified";
  const words = value.replace(/_/g, " ");
  return words.startsWith("fx") ? "FX" + words.slice(2) : words[0].toUpperCase() + words.slice(1);
};

// Anything from the data files is text we did not write, so build elements
// with textContent instead of innerHTML where the value could contain markup.
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

// --- Loading ----------------------------------------------------------------

async function loadJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

async function loadTrace(caseId) {
  if (!state.traces[caseId]) {
    state.traces[caseId] = await loadJSON(`data/traces/${caseId}.json`);
  }
  return state.traces[caseId];
}

// --- Overview ---------------------------------------------------------------

function metric(value, label, sub) {
  const card = el("div", "metric");
  card.append(el("div", "value", value), el("div", "label", label));
  if (sub) card.append(el("div", "sub", sub));
  return card;
}

function renderOverview() {
  const { reconciliation: rec, eval: evaluation, break_types: types } = state.summary;

  const headline = document.getElementById("headline");
  headline.textContent = "";
  headline.append(
    metric(percent(rec.bank_match_rate), "Matched by rules",
           `${rec.matched_pairs} of ${rec.bank_lines} bank lines · ${percent(rec.value_match_rate)} by value`),
    metric(String(rec.exception_cases), "Exceptions to investigate",
           `${money(rec.break_value)} of differences`),
    metric(percent(evaluation.classification_accuracy, 0), "Agent accuracy",
           `${evaluation.cases}/${evaluation.cases} type and entry correct`),
    metric(money(evaluation.total_cost_usd), "Cost per run",
           `${money(evaluation.cost_per_case_usd)} per case · ${evaluation.median_seconds.toFixed(0)}s median`),
  );

  const body = document.querySelector("#break-types tbody");
  body.textContent = "";
  for (const row of types) {
    const tr = el("tr");
    tr.append(
      el("td", null, typeLabel(row.exception_type)),
      el("td", "num", String(row.cases)),
      el("td", "num", money(row.break_value)),
      el("td", "num", percent(row.share_of_value)),
      el("td", "num", row.cases_needing_an_entry === 0 ? "none" : `${row.cases_needing_an_entry} of ${row.cases}`),
      el("td", "num", money(row.agent_cost_usd)),
    );
    body.append(tr);
  }

  document.getElementById("run-meta").textContent =
    `${state.summary.model} · run ${state.summary.run_id}`;
}

// --- Case list --------------------------------------------------------------

function renderCaseList() {
  const list = document.getElementById("case-list");
  list.textContent = "";

  for (const item of state.cases) {
    const button = el("button");
    button.type = "button";
    button.dataset.caseId = item.case_id;
    button.setAttribute("aria-current", String(item.case_id === state.selectedCase));

    // A tick/cross so the grade is visible without opening the case.
    const verdict = item.classification_correct && item.fix_correct;
    const meta = el("div", "case-meta");
    meta.append(
      el("span", null, `${verdict ? "✓" : "✗"} ${typeLabel(item.classification)}`),
      el("span", null, money(item.break_value)),
    );
    button.append(el("div", "case-id", item.case_id), meta);
    button.addEventListener("click", () => selectCase(item.case_id));

    const li = el("li");
    li.append(button);
    list.append(li);
  }
}

// --- Case detail ------------------------------------------------------------

function factCard(title, pairs) {
  const card = el("dl", "fact-card");
  card.append(el("dt", null, title));
  for (const [label, value] of pairs) {
    card.append(el("dd", null, `${label}: ${value}`));
  }
  return card;
}

function renderEntry(lines) {
  if (!lines.length) {
    return el("p", "note", "No correcting entry — the agent judged that nothing needs posting.");
  }
  const table = el("table");
  const head = el("thead");
  const headRow = el("tr");
  headRow.append(el("th", null, "Account"), el("th", "num", "Debit"), el("th", "num", "Credit"), el("th", null, "Memo"));
  head.append(headRow);
  const body = el("tbody");
  for (const line of lines) {
    const tr = el("tr");
    tr.append(
      el("td", null, line.account),
      el("td", "num", Number(line.debit) ? money(line.debit) : ""),
      el("td", "num", Number(line.credit) ? money(line.credit) : ""),
      el("td", null, line.memo || ""),
    );
    body.append(tr);
  }
  table.append(head, body);
  const scroll = el("div", "table-scroll");
  scroll.append(table);
  return scroll;
}

function renderTrace(trace) {
  const container = el("div");
  for (const step of trace.steps) {
    const details = el("details", "step");
    const summary = el("summary");
    const calls = step.tool_calls.map((call) => call.name).join(", ") || "final answer";
    summary.append(
      el("span", null, `Step ${step.step} · ${calls}`),
      el("span", null, `${step.model_seconds}s · ${money(step.cost_usd)}`),
    );
    details.append(summary);

    const bodyEl = el("div", "step-body");
    for (const thought of step.thinking) bodyEl.append(el("p", "thinking", thought));
    for (const text of step.text) bodyEl.append(el("p", null, text));
    for (const call of step.tool_calls) {
      bodyEl.append(el("p", "tool-name", `${call.name}(${JSON.stringify(call.input)})`));
    }
    for (const result of step.tool_results) {
      const pre = el("pre", null, result.text + (result.truncated ? "\n… (truncated for this demo)" : ""));
      if (result.is_error) pre.classList.add("error");
      bodyEl.append(pre);
    }
    details.append(bodyEl);
    container.append(details);
  }
  return container;
}

async function renderCaseDetail(caseId) {
  const detail = document.getElementById("case-detail");
  const item = state.cases.find((row) => row.case_id === caseId);
  detail.textContent = "";

  const heading = el("h3", null, `${item.case_id} · ${typeLabel(item.classification)}`);
  detail.append(heading);

  const grade = el("p");
  const verdict = item.classification_correct && item.fix_correct;
  const pill = el("span", `pill ${verdict ? "pill-good" : "pill-bad"}`,
    verdict ? "Graded correct — type and entry" : "Graded incorrect");
  grade.append(pill, el("span", null, `  Answer key: ${typeLabel(item.expected_type)}`));
  detail.append(grade);

  detail.append(el("h4", null, "The exception"));
  const facts = el("div", "facts");
  facts.append(
    factCard("Bank", [
      ["ID", item.bank_txn_id || "— none —"],
      ["Amount", money(item.bank_amount)],
      ["Reference", item.reference || "none"],
    ]),
    factCard("Ledger", [
      ["ID", item.gl_entry_id || "— none —"],
      ["Amount", money(item.ledger_amount)],
      ["Currency", item.ledger_currency || "USD"],
    ]),
    factCard("Difference", [
      ["Bank − ledger", money(item.amount_difference)],
      ["Money at stake", money(item.break_value)],
      ["Shape", item.case_shape.replace(/_/g, " ")],
    ]),
  );
  detail.append(facts);

  detail.append(el("h4", null, "Proposed correcting entry"));
  detail.append(renderEntry(item.lines));

  detail.append(el("h4", null, "Why"));
  detail.append(el("div", "explanation", item.explanation || "—"));
  detail.append(el("p", "note", `Evidence cited: ${item.evidence || "—"}`));

  detail.append(el("h4", null, "How the agent got there"));
  const trace = await loadTrace(caseId);
  detail.append(el("p", "note",
    `${trace.steps.length} steps · ${trace.totals.tool_calls} tool calls · ` +
    `${trace.latency_seconds}s · ${money(trace.totals.cost_usd)}`));
  detail.append(renderTrace(trace));
}

function selectCase(caseId) {
  state.selectedCase = caseId;
  for (const button of document.querySelectorAll("#case-list button")) {
    button.setAttribute("aria-current", String(button.dataset.caseId === caseId));
  }
  renderCaseDetail(caseId);
}

// --- Evaluation -------------------------------------------------------------

function renderEvaluation() {
  const evaluation = state.summary.eval;

  const headline = document.getElementById("eval-headline");
  headline.textContent = "";
  headline.append(
    metric(percent(evaluation.classification_accuracy, 0), "Exception type correct",
           `${Math.round(evaluation.classification_accuracy * evaluation.cases)} of ${evaluation.cases} cases`),
    metric(percent(evaluation.fix_accuracy, 0), "Proposed entry correct",
           "cash effect matched to the cent"),
    metric(money(evaluation.cost_per_case_usd), "Cost per case",
           `${money(evaluation.total_cost_usd)} for the run · ${evaluation.tool_calls} tool calls`),
    metric(`${evaluation.median_seconds.toFixed(0)}s`, "Median time per case",
           "mostly the model thinking, not the database"),
  );

  const byType = document.querySelector("#eval-by-type tbody");
  byType.textContent = "";
  for (const row of evaluation.by_type) {
    const tr = el("tr");
    tr.append(
      el("td", null, typeLabel(row.expected_type)),
      el("td", "num", String(row.total)),
      el("td", "num", String(row.correct)),
      el("td", "num", percent(row.accuracy, 0)),
    );
    byType.append(tr);
  }

  renderConfusion(evaluation.confusion);
}

function renderConfusion({ types, predicted, rows }) {
  const table = document.getElementById("eval-confusion");
  const head = table.querySelector("thead");
  const body = table.querySelector("tbody");
  head.textContent = "";
  body.textContent = "";

  const headRow = el("tr");
  headRow.append(el("th", null, "True type ↓ / said →"));
  for (const name of predicted) headRow.append(el("th", "num", typeLabel(name)));
  head.append(headRow);

  types.forEach((trueType, rowIndex) => {
    const tr = el("tr");
    tr.append(el("th", null, typeLabel(trueType)));
    predicted.forEach((predictedType, columnIndex) => {
      const count = rows[rowIndex][columnIndex];
      // The diagonal (said what it was) is highlighted so the shape of the
      // result is readable without doing the comparison in your head.
      const onDiagonal = trueType === predictedType;
      const cell = el("td", `num cell${onDiagonal ? " diagonal" : count ? " mistake" : ""}`,
                      count ? String(count) : "·");
      tr.append(cell);
    });
    body.append(tr);
  });
}

// --- Tabs (kept in the URL, so a section can be linked and survives reload) ---

function showTab(name) {
  for (const tab of document.querySelectorAll(".tabs button")) {
    const selected = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(selected));
    document.getElementById(tab.dataset.tab).hidden = !selected;
  }
}

function setupTabs() {
  for (const tab of document.querySelectorAll(".tabs button")) {
    tab.addEventListener("click", () => {
      window.location.hash = tab.dataset.tab;      // triggers hashchange below
    });
  }
  const fromUrl = () => {
    const name = window.location.hash.replace("#", "");
    showTab(document.getElementById(name) ? name : "overview");
  };
  window.addEventListener("hashchange", fromUrl);
  fromUrl();
}

// --- Start ------------------------------------------------------------------

async function start() {
  setupTabs();
  try {
    const [summary, cases] = await Promise.all([
      loadJSON("data/summary.json"),
      loadJSON("data/cases.json"),
    ]);
    state.summary = summary;
    state.cases = cases;

    renderOverview();
    renderEvaluation();
    renderCaseList();
    selectCase(cases[0].case_id);
  } catch (error) {
    document.getElementById("headline").textContent =
      `Could not load the demo data (${error.message}). If you opened this file directly, ` +
      `serve it instead: cd web && python -m http.server 8000`;
  }
}

start();
