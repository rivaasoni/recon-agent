"""
Human-in-the-loop review UI — Phase 7.

A reviewer sees each exception case, the agent's proposed fix, and the
reasoning behind it, then approves or rejects (Step 3).

Run it from the project root:
    streamlit run app/review_app.py

How Streamlit works: this whole script re-runs top to bottom every time you
interact with the page. So anything that must survive an interaction lives
either in st.session_state (this browser session) or on disk (the decision
log). Nothing important is kept in a plain variable.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run app/review_app.py` puts THIS folder first on the import path,
# not the project root — so `import recon` would fail without this line.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from recon.review.store import (  # noqa: E402
    APPROVED,
    REJECTED,
    approved_entries,
    decision_history,
    entries_csv,
    record_decision,
    review_items,
    review_metrics,
)

STATUS_ICONS = {"pending": "🟡", "approved": "🟢", "rejected": "🔴", "no_proposal": "⚪"}

st.set_page_config(page_title="Reconciliation Exceptions", page_icon="🏦", layout="wide")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def money(value) -> str:
    """-12241.08 -> '-12,241.08'; None -> '—'."""
    return "—" if value is None else f"{float(value):,.2f}"


def fact_table(pairs: list[tuple[str, str]]) -> None:
    """Show label/value pairs as a simple two-column table."""
    st.table({"": [label for label, _ in pairs], " ": [value for _, value in pairs]})


# ---------------------------------------------------------------------------
# Sidebar: who is reviewing, and which case
# ---------------------------------------------------------------------------
def sidebar(items: list[dict]) -> dict | None:
    st.sidebar.title("Review queue")

    # session_state remembers this across re-runs of the script.
    st.session_state.setdefault("reviewer", "")
    st.sidebar.text_input("Your name (recorded with each decision)", key="reviewer")

    chosen_statuses = st.sidebar.multiselect(
        "Show statuses", list(STATUS_ICONS), default=["pending"],
        help="Decided cases are hidden by default — tick a status to see them again.",
    )
    classifications = sorted({item["proposal"]["classification"]
                              for item in items if item["proposal"]})
    chosen_types = st.sidebar.multiselect(
        "Exception type", classifications, default=classifications,
        help="Useful for reviewing one type at a time — they need the same checks.",
    )

    visible = [
        item for item in items
        if item["status"] in chosen_statuses
        and (item["proposal"] is None or item["proposal"]["classification"] in chosen_types)
    ]
    if not visible:
        st.sidebar.info("No cases with the selected statuses.")
        return None

    def label(item: dict) -> str:
        classification = item["proposal"]["classification"] if item["proposal"] else "no proposal"
        return f"{STATUS_ICONS[item['status']]} {item['case_id']} · {classification}"

    return st.sidebar.radio("Case", visible, format_func=label, label_visibility="collapsed")


# ---------------------------------------------------------------------------
# Main panel: the case, the proposal, the reasoning
# ---------------------------------------------------------------------------
def show_case_facts(case: dict) -> None:
    st.subheader("The exception")
    st.caption("What the rule-based matcher found. Facts only — no classification.")

    left, right = st.columns(2)
    with left:
        st.markdown("**Bank**")
        if case["bank_txn_id"]:
            fact_table([
                ("ID", case["bank_txn_id"]),
                ("Date", str(case["bank_date"])),
                ("Description", case["bank_description"]),
                ("Amount (USD)", money(case["bank_amount"])),
            ])
        else:
            st.info("No bank line — nothing cleared the bank for this case.")
    with right:
        st.markdown("**Ledger**")
        if case["gl_entry_id"]:
            fact_table([
                ("ID", case["gl_entry_id"]),
                ("Date", str(case["ledger_date"])),
                ("Counterparty", case["ledger_counterparty"]),
                ("Description", case["ledger_description"]),
                ("Amount (USD)", money(case["ledger_amount"])),
                ("Currency", case["ledger_currency"] or "USD"),
                ("FX rate used", money(case["ledger_fx_rate"])),
            ])
        else:
            st.info("No ledger entry — nothing was recorded for this case.")

    st.markdown(
        f"**Shape:** `{case['case_shape']}` · **Reference:** {case['reference'] or '—'} · "
        f"**Bank − ledger:** {money(case['amount_difference'])} · "
        f"**Reference matched elsewhere:** {'yes' if case['reference_matched_elsewhere'] else 'no'}"
    )


def show_proposal(proposal: dict | None) -> None:
    st.subheader("The agent's proposal")
    if proposal is None:
        st.warning("The agent produced no proposal for this case. It still needs a human.")
        return

    st.markdown(f"**Classification:** `{proposal['classification']}`")

    lines = proposal["lines"]
    if lines:
        st.markdown("**Proposed correcting entry**")
        st.dataframe(
            [{"Account": line["account"],
              "Debit": line["debit"] if float(line["debit"]) else "",
              "Credit": line["credit"] if float(line["credit"]) else "",
              "Memo": line["memo"]} for line in lines],
            hide_index=True, width="stretch",   # (use_container_width is deprecated)
        )
        st.caption(f"Total {proposal['total']} — debits equal credits (checked by the tool).")
    else:
        st.info("**No correcting entry proposed.** The agent judged that nothing needs posting.")

    st.markdown("**Why**")
    st.write(proposal["explanation"])
    st.markdown(f"**Evidence cited:** {', '.join(proposal['evidence']) or '—'}")
    st.caption(f"Proposal {proposal['proposal_id']} · status in file: {proposal['status']}")


def show_trace(trace: dict | None) -> None:
    st.subheader("How the agent got there")
    if trace is None:
        st.info("No trace found for this case.")
        return

    totals = trace["totals"]
    a, b, c, d = st.columns(4)
    a.metric("Status", trace["status"])
    b.metric("Steps", len(trace["steps"]))
    c.metric("Tool calls", totals.get("tool_calls", 0))
    d.metric("Cost", f"${totals.get('cost_usd', 0):.4f}")

    for step in trace["steps"]:
        header = f"Step {step['step']} · {step['stop_reason']} · {step['model_seconds']}s"
        with st.expander(header):
            for thought in step["thinking"]:
                st.markdown(f"*Thinking:* {thought}")
            for text in step["text"]:
                st.markdown(text)
            for call in step["tool_calls"]:
                st.markdown(f"**Called** `{call['name']}`")
                st.json(call["input"], expanded=False)
            for result in step["tool_results"]:
                label = "Tool error" if result["is_error"] else "Result"
                st.markdown(f"*{label}:*")
                st.code(result["text"][:2000], language="json")


def show_decision(item: dict) -> None:
    """Approve / Reject, plus the history of earlier decisions."""
    st.subheader("Your decision")
    proposal = item["proposal"]
    reviewer = st.session_state.get("reviewer", "").strip()

    if proposal is None:
        st.info("Nothing to approve: the agent made no proposal. Handle this case manually.")
        return

    current = item["decision"]
    if current:
        st.info(f"Currently **{current['decision']}** by {current['reviewer']} "
                f"on {current['decided_at']}"
                + (f" — “{current['note']}”" if current["note"] else ""))
        st.caption("Deciding again adds a new record; earlier decisions are kept.")

    # A separate key per case, so a note typed on one case can't appear on another.
    note = st.text_area("Note (required when rejecting)", key=f"note_{item['case_id']}")

    if not reviewer:
        st.warning("Enter your name in the sidebar before approving or rejecting.")

    approve_col, reject_col = st.columns(2)
    approved = approve_col.button("✅ Approve", type="primary",
                                  disabled=not reviewer, width="stretch")
    rejected = reject_col.button("❌ Reject", disabled=not reviewer, width="stretch")

    if approved or rejected:
        decision = APPROVED if approved else REJECTED
        # Approving may be silent; rejecting must say why — that reason is the
        # feedback that shows where the agent went wrong.
        if rejected and not note.strip():
            st.error("Please write a note explaining the rejection.")
            return
        record_decision(proposal["proposal_id"], item["case_id"], decision,
                        reviewer=reviewer, note=note)
        st.success(f"Recorded: {decision}. Nothing has been posted to the ledger.")
        # Redraw so the counts, the status icon and the filter all update.
        st.rerun()

    history = decision_history(proposal["proposal_id"])
    if len(history) > 1:
        with st.expander(f"Decision history ({len(history)})"):
            for record in history:
                st.markdown(f"- **{record['decision']}** · {record['reviewer']} · "
                            f"{record['decided_at']} · {record['note'] or '—'}")


def show_overview_and_export(items: list[dict], metrics: dict) -> None:
    """All cases at a glance, plus the hand-off file for approved entries."""
    with st.expander("All cases + export approved entries"):
        st.dataframe(
            [{
                "Case": item["case_id"],
                "Status": item["status"],
                "Type": item["proposal"]["classification"] if item["proposal"] else "—",
                "Reference": item["case"]["reference"] or "—",
                "Entry total": item["proposal"]["total"] if item["proposal"] else "—",
                "Reviewer": item["decision"]["reviewer"] if item["decision"] else "—",
                "Note": item["decision"]["note"] if item["decision"] else "",
            } for item in items],
            hide_index=True, width="stretch",
        )

        rows = approved_entries(items)
        st.download_button(
            f"⬇️ Download {len(rows)} approved journal lines (CSV)",
            data=entries_csv(rows),
            file_name="approved_journal_entries.csv",
            mime="text/csv",
            disabled=not rows,
        )
        st.caption(
            "This file is for a person to post in the accounting system — "
            "nothing is posted from here."
            + (f" {metrics['no_entry_approved']} approved case(s) need no entry, "
               "so they contribute no lines." if metrics["no_entry_approved"] else "")
        )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def main() -> None:
    st.title("🏦 Reconciliation exceptions — human review")
    st.caption("All data is synthetic. Approving a proposal records a decision; "
               "it never posts anything to the ledger.")

    items = review_items()
    metrics = review_metrics(items)
    counts = metrics["counts"]

    a, b, c, d = st.columns(4)
    a.metric("Pending", counts["pending"], help="Cases still waiting for a human")
    b.metric("Approved", counts["approved"])
    c.metric("Rejected", counts["rejected"])
    d.metric("No proposal", counts["no_proposal"])

    e, f, g = st.columns(3)
    e.metric("Value pending", f"${metrics['pending_value']:,.2f}",
             help="Total size of the corrections still awaiting review")
    f.metric("Value approved", f"${metrics['approved_value']:,.2f}")
    g.metric("Agent cost", f"${metrics['agent_cost_usd']:.2f}",
             help=f"{metrics['agent_seconds']:.0f}s of agent time across all cases")

    show_overview_and_export(items, metrics)
    selected = sidebar(items)
    if selected is None:
        return

    st.divider()
    st.header(f"{STATUS_ICONS[selected['status']]} {selected['case_id']}")
    show_case_facts(selected["case"])
    st.divider()
    show_proposal(selected["proposal"])
    st.divider()
    show_decision(selected)
    st.divider()
    show_trace(selected["trace"])


main()
