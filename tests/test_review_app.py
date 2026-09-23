"""Tests for the Streamlit review UI — Phase 7, Step 5.

AppTest runs the app script headlessly (no browser), lets us set inputs and
click buttons, and exposes what the page rendered. These tests cover the
WIRING: the store's rules are tested in test_review_store.py, and here we
check the UI actually applies them.

The app reads data through recon.review.store, whose `settings` the
temp_settings fixture points at a throwaway folder — so these tests never
touch your real proposals or decisions.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

# Helpers from the store tests (pytest puts tests/ on the import path).
from test_review_store import add_proposal, add_trace

from recon.review.store import load_decisions

APP = str(Path(__file__).resolve().parent.parent / "app" / "review_app.py")


def start_app() -> AppTest:
    """Run the app once, as if a reviewer had just opened it."""
    return AppTest.from_file(APP, default_timeout=60).run()


def labels(elements) -> list[str]:
    return [element.label for element in elements]


@pytest.fixture
def one_pending_case(tiny_warehouse):
    """The tiny warehouse plus one proposal and trace for CASE-001."""
    add_proposal(tiny_warehouse, "CASE-001", "PROP-A")
    add_trace(tiny_warehouse, "CASE-001")
    return tiny_warehouse


# ---------------------------------------------------------------------------
# What the reviewer sees
# ---------------------------------------------------------------------------
def test_page_shows_the_queue_and_the_headline_numbers(one_pending_case):
    app = start_app()

    assert not app.exception
    assert "human review" in app.title[0].value
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Pending"] == "1"
    assert metrics["No proposal"] == "2"        # the other two cases
    assert app.sidebar.radio[0].options == ["🟡 CASE-001 · fx_difference"]


def test_case_detail_shows_facts_proposal_and_trace(one_pending_case):
    app = start_app()

    text = " ".join(str(element.value) for element in app.markdown)
    assert "BILL-5059" in text                   # the case reference
    assert "fx_difference" in text               # the classification
    assert "BNK-0055, DOC-002" in text           # evidence cited
    assert app.subheader[-1].value == "How the agent got there"


def test_a_case_with_no_proposal_tells_the_reviewer_to_handle_it(one_pending_case):
    app = start_app()
    app.sidebar.multiselect[0].set_value(["no_proposal"]).run()

    messages = " ".join(info.value for info in app.info)
    assert "no proposal" in messages.lower()


# ---------------------------------------------------------------------------
# Safety rules, enforced in the UI
# ---------------------------------------------------------------------------
def test_buttons_are_disabled_until_a_reviewer_is_named(one_pending_case):
    app = start_app()
    assert labels(app.button) == ["✅ Approve", "❌ Reject"]
    assert all(button.disabled for button in app.button)

    app.sidebar.text_input[0].set_value("Rivaa").run()
    assert not any(button.disabled for button in app.button)


def test_rejecting_without_a_note_records_nothing(one_pending_case):
    app = start_app()
    app.sidebar.text_input[0].set_value("Rivaa").run()

    app.button[1].click().run()          # Reject, with an empty note

    assert "note explaining the rejection" in app.error[0].value
    assert load_decisions() == []


def test_approving_records_a_decision_and_updates_the_page(one_pending_case):
    app = start_app()
    app.sidebar.text_input[0].set_value("Rivaa").run()

    app.button[0].click().run()          # Approve

    [decision] = load_decisions()
    assert decision["decision"] == "approved"
    assert decision["case_id"] == "CASE-001"
    assert decision["reviewer"] == "Rivaa"
    metrics = {metric.label: metric.value for metric in app.metric}
    assert (metrics["Pending"], metrics["Approved"]) == ("0", "1")


def test_rejecting_with_a_note_records_the_reason(one_pending_case):
    app = start_app()
    app.sidebar.text_input[0].set_value("Rivaa").run()
    app.text_area[0].set_value("Wrong account — should hit AP.").run()

    app.button[1].click().run()          # Reject

    [decision] = load_decisions()
    assert decision["decision"] == "rejected"
    assert decision["note"] == "Wrong account — should hit AP."


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def test_export_button_activates_once_something_is_approved(one_pending_case):
    app = start_app()
    download = app.download_button[0]
    assert download.disabled and "0 approved" in download.label

    app.sidebar.text_input[0].set_value("Rivaa").run()
    app.button[0].click().run()

    download = app.download_button[0]
    assert not download.disabled
    assert "2 approved journal lines" in download.label     # the entry's two lines


def test_empty_queue_tells_a_newcomer_to_run_the_agent(tiny_warehouse):
    """A fresh clone has cases but no proposals. 'No cases' would be true but
    useless; the app should say what to do."""
    app = start_app()

    messages = " ".join(info.value for info in app.sidebar.info)
    assert "agent hasn't run yet" in messages
    assert "python -m recon.agent.run_all" in messages
