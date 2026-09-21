"""Tests for the Phase 2 synthetic data generator.

Most of these check PROPERTIES that must always hold ("every ID is unique",
"no document leaks a label") rather than exact values ("row 17 is 4,572.10").
Property tests survive harmless changes and still catch real bugs.
"""

import random

import pandas as pd
import pytest

from recon.config import settings
from recon.data_gen import generate
from recon.data_gen.generate import (
    PRIVATE_COLUMNS,
    build_dataset,
    build_documents,
    check_answer_key,
    transpose_digits,
)

EXPECTED_TYPES = {
    "timing_difference",
    "duplicate",
    "bank_fee",
    "fx_difference",
    "missing_ledger_entry",
    "amount_mismatch",
}


# ---------------------------------------------------------------------------
# Fixtures: shared setup that pytest hands to any test that asks for it
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def dataset():
    """Build the dataset once and share it across tests in this file.

    scope="module" means "build once per file", not once per test — the
    generator is deterministic, so rebuilding it every time would just be slow.
    """
    month, bank, ledger, key = build_dataset(settings.random_seed)
    docs = build_documents(month, bank, ledger, settings.random_seed)
    return {"month": month, "bank": bank, "ledger": ledger, "key": key, "docs": docs}


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
def test_same_seed_gives_identical_data(dataset):
    """The whole point of the seed: the answer key only means something if
    the data underneath it never changes between runs."""
    _, bank, ledger, key = build_dataset(settings.random_seed)
    pd.testing.assert_frame_equal(bank, dataset["bank"])
    pd.testing.assert_frame_equal(ledger, dataset["ledger"])
    pd.testing.assert_frame_equal(key, dataset["key"])


def test_different_seed_gives_different_data(dataset):
    """If a new seed gave the same data, the seed wouldn't be doing anything."""
    _, other_bank, _, _ = build_dataset(settings.random_seed + 1)
    assert not other_bank["amount"].equals(dataset["bank"]["amount"])


# ---------------------------------------------------------------------------
# Shape of the bank and ledger data
# ---------------------------------------------------------------------------
def test_ids_are_unique(dataset):
    assert dataset["bank"]["bank_txn_id"].is_unique
    assert dataset["ledger"]["gl_entry_id"].is_unique


def test_no_weekend_dates(dataset):
    """Banks don't post on weekends. weekday() 5 and 6 are Saturday and Sunday."""
    for dates in (dataset["bank"]["value_date"], dataset["ledger"]["posting_date"]):
        assert all(d.weekday() < 5 for d in dates)


def test_all_dates_inside_the_month(dataset):
    """Timing differences clear in September, so they must NOT appear here."""
    for dates in (dataset["bank"]["value_date"], dataset["ledger"]["posting_date"]):
        assert all(generate.MONTH_START <= d <= generate.MONTH_END for d in dates)


# ---------------------------------------------------------------------------
# The answer key
# ---------------------------------------------------------------------------
def test_all_six_exception_types_are_seeded(dataset):
    assert set(dataset["key"]["exception_type"]) == EXPECTED_TYPES


def test_every_tagged_row_is_in_the_answer_key(dataset):
    """No broken row may be missing from the key — an unlisted exception
    would make the agent look wrong when it is actually right."""
    tagged = pd.concat([dataset["bank"], dataset["ledger"]])["exception_id"].dropna()
    assert set(tagged) == set(dataset["key"]["exception_id"])


def test_answer_key_balances(dataset):
    """Should run without raising (it raises RuntimeError if it doesn't balance)."""
    check_answer_key(dataset["bank"], dataset["ledger"], dataset["key"])


def test_answer_key_check_catches_a_missing_exception(dataset):
    """A check that can never fail proves nothing. Delete one exception from
    the key and make sure check_answer_key actually complains."""
    key_missing_one = dataset["key"][dataset["key"]["exception_type"] != "bank_fee"]
    with pytest.raises(RuntimeError, match="does not balance"):
        check_answer_key(dataset["bank"], dataset["ledger"], key_missing_one)


def test_timing_differences_need_no_entry(dataset):
    """They clear on their own next month. 'Fixing' one would be a mistake."""
    key = dataset["key"]
    timing = key[key["exception_type"] == "timing_difference"]
    assert (timing["expected_action"] == "no_entry").all()
    assert (timing["cash_adjustment"] == 0).all()


# ---------------------------------------------------------------------------
# Transposition errors
# ---------------------------------------------------------------------------
def test_transposition_difference_is_divisible_by_9():
    """Try 500 random amounts. Every typo must differ from the original, and
    the difference (in cents) must be divisible by 9."""
    rng = random.Random(0)
    for _ in range(500):
        original = rng.randint(1_000, 5_000_000) / 100   # 10.00 to 50,000.00
        if len(set(f"{original:.2f}".replace(".", ""))) == 1:
            continue  # e.g. 111.11 — every digit the same, nothing to swap
        typo = transpose_digits(original, rng)
        diff_cents = round(abs(typo - original) * 100)
        assert diff_cents != 0
        assert diff_cents % 9 == 0


# ---------------------------------------------------------------------------
# Supporting documents
# ---------------------------------------------------------------------------
def test_documents_never_leak_the_answer(dataset):
    """Documents state facts. They must never name the classification."""
    forbidden = ["EXC-", "exception", "duplicate", "mismatch", "timing", "fx_difference"]
    for text in dataset["docs"]:
        for word in forbidden:
            assert word.lower() not in text.lower(), f"'{word}' leaked into:\n{text}"


def test_every_exception_reference_has_a_document(dataset):
    """The agent must be able to find evidence for each exception. (Bank fees
    have no reference; the fee schedule covers them.)"""
    all_docs = "\n".join(dataset["docs"])
    for reference in dataset["key"]["reference"]:
        if reference != "(none)":
            assert reference in all_docs, f"No document mentions {reference}"


def test_normal_transactions_have_documents_too(dataset):
    """Noise check: if only exceptions had paperwork, having a document
    would give the answer away."""
    all_docs = "\n".join(dataset["docs"])
    exception_refs = set(dataset["key"]["reference"])
    normal_refs = set(dataset["ledger"]["reference"]) - exception_refs
    assert sum(ref in all_docs for ref in normal_refs) >= 10


# ---------------------------------------------------------------------------
# End to end: run main() and inspect the files it writes.
# The temp_settings fixture lives in tests/conftest.py (shared with other files).
# ---------------------------------------------------------------------------
def test_main_writes_all_outputs(temp_settings):
    generate.main()

    assert (temp_settings.raw_dir / "bank_statement.csv").exists()
    assert (temp_settings.raw_dir / "general_ledger.csv").exists()
    assert (temp_settings.eval_dir / "answer_key.csv").exists()
    assert len(list(temp_settings.documents_dir.glob("DOC-*.txt"))) > 0


def test_csvs_contain_no_private_columns(temp_settings):
    """The ground-truth columns must never reach the files the agent reads."""
    generate.main()

    for name in ("bank_statement.csv", "general_ledger.csv"):
        columns = pd.read_csv(temp_settings.raw_dir / name).columns
        leaked = set(PRIVATE_COLUMNS) & set(columns)
        assert not leaked, f"{name} leaked private columns: {leaked}"


def test_answer_key_is_not_in_raw_folder(temp_settings):
    """Phase 3 loads data/raw/ into the warehouse. The key must not be there."""
    generate.main()

    assert not list(temp_settings.raw_dir.rglob("answer_key*"))
