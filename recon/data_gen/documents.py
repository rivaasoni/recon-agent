"""
Supporting documents — Phase 2, Step 4.

What this produces
------------------
A folder of small text files in data/raw/documents/, one per document:

    - the bank's fee schedule
    - customer invoices and vendor bills
    - international wire confirmations from the bank
    - a customer remittance advice / our own AP payment run

In Phase 5 the agent gets a tool to search this folder. It is how the agent
backs up a classification with EVIDENCE instead of a guess.

Two rules keep this honest:

  1. Documents state FACTS, never conclusions. A wire confirmation says
     "converted at 1.3022", never "this is an FX difference". The agent has
     to connect the dots itself.
  2. Normal transactions get documents too ("noise"). If only exceptions had
     paperwork, the mere existence of a document would give the answer away.

ALL DATA IS SYNTHETIC. The bank and every counterparty are invented.
"""

from __future__ import annotations

import random
from datetime import timedelta

import pandas as pd

from recon.config import settings

# An obviously invented bank name.
BANK_NAME = "Fictional Community Bank"

# How many ordinary (non-exception) invoices/bills to add as noise.
N_NOISE_REFERENCES = 12

MONTHLY_SERVICE_CHARGE = 45.00
INTL_WIRE_FEE = 35.00


def money(currency: str, amount: float) -> str:
    """Format money the way a document would: 'USD 1,234.56' (no minus sign)."""
    return f"{currency} {abs(amount):,.2f}"


# ---------------------------------------------------------------------------
# One function per document type. Each returns the document's text.
# ---------------------------------------------------------------------------
def fee_schedule() -> str:
    return "\n".join([
        f"DOCUMENT: {BANK_NAME} — Business Checking Fee Schedule",
        "Effective: 2026-01-01",
        "",
        f"Monthly account service charge ........ USD {MONTHLY_SERVICE_CHARGE:.2f}, debited on the last business day of the month",
        "Incoming ACH credit ................... no charge",
        "Outgoing ACH debit .................... no charge",
        f"Outgoing international wire ........... first wire each calendar month free, then USD {INTL_WIRE_FEE:.2f} per wire",
        "",
        "International wires are converted to USD at the bank's rate on the value date.",
        "Fees are debited as separate line items on the statement.",
    ])


def invoice_or_bill(facts: dict) -> str:
    """A customer invoice (INV-...) or a vendor bill (BILL-...)."""
    is_invoice = facts["reference"].startswith("INV")
    lines = [
        "DOCUMENT: Customer invoice" if is_invoice else "DOCUMENT: Vendor bill",
        f"{'Invoice' if is_invoice else 'Bill'} number: {facts['reference']}",
        f"{'Customer' if is_invoice else 'Vendor'}: {facts['counterparty']}",
        f"Issue date: {facts['issue_date']}",
        f"Due date: {facts['issue_date'] + timedelta(days=30)}",
        f"Amount due: {money(facts['currency'], facts['doc_amount'])}",
        "Terms: Net 30",
    ]
    return "\n".join(lines)


def wire_confirmation(bank_row: pd.Series, ledger_row: pd.Series, fee_charged: bool) -> str:
    """The bank's confirmation of an outgoing international wire."""
    foreign_amount = ledger_row["foreign_amount"]
    usd = abs(bank_row["amount"])
    # Recover the rate the bank used. (It is also printed in the bank
    # description; computing it here keeps the two consistent.)
    rate = round(usd / foreign_amount, 4)
    fee_line = (
        f"Wire fee: USD {INTL_WIRE_FEE:.2f}, debited separately"
        if fee_charged
        else "Wire fee: USD 0.00 (first international wire this month)"
    )
    return "\n".join([
        f"DOCUMENT: {BANK_NAME} — Outgoing International Wire Confirmation",
        f"Value date: {bank_row['value_date']}",
        f"Beneficiary: {ledger_row['counterparty']}",
        f"Payment reference: {bank_row['reference']}",
        f"Amount sent: {money(ledger_row['currency'], foreign_amount)}",
        f"Exchange rate applied: {rate:.4f}",
        f"USD debited from account: {usd:,.2f}",
        fee_line,
    ])


def customer_remittance(ledger_row: pd.Series) -> str:
    """A customer telling us they have sent a payment."""
    sent = ledger_row["posting_date"]
    return "\n".join([
        "DOCUMENT: Customer remittance advice",
        f"From: {ledger_row['counterparty']}",
        f"Date sent: {sent}",
        f"Paying invoice: {ledger_row['reference']}",
        f"Amount: {money('USD', ledger_row['amount'])}",
        f"Payment method: ACH, initiated {sent}. Please allow 1–2 business days for settlement.",
    ])


def ap_payment_run(ledger_row: pd.Series) -> str:
    """Our own accounts-payable team's record of a scheduled payment."""
    return "\n".join([
        "DOCUMENT: Accounts payable payment run",
        f"Run date: {ledger_row['posting_date']}",
        f"Bill: {ledger_row['reference']}",
        f"Vendor: {ledger_row['counterparty']}",
        f"Amount: {money('USD', ledger_row['amount'])}",
        "Payment method: ACH",
        # Our generator dates these on the last business days of August, so
        # they settle on the first business day of September.
        "Scheduled settlement date: 2026-09-01",
    ])


# ---------------------------------------------------------------------------
# Gathering the facts about one reference
# ---------------------------------------------------------------------------
def reference_facts(reference: str, bank: pd.DataFrame, ledger: pd.DataFrame,
                    names_by_upper: dict[str, str], rng: random.Random) -> dict:
    """Everything an invoice/bill needs to know about one reference.

    Where the bank and ledger disagree, the document shows the TRUE amount:
    the bank's (money really moved). That is what makes a document useful
    evidence against a typo in the ledger.
    """
    bank_rows = bank[bank["reference"] == reference]
    ledger_rows = ledger[ledger["reference"] == reference]

    if len(ledger_rows):
        first = ledger_rows.iloc[0]
        counterparty = first["counterparty"]
        currency = first["currency"]
        event_date = first["posting_date"]
    else:
        # Missing ledger entry: only the bank knows about it. Recover the name
        # from a description like "ACH CREDIT SOME COMPANY LLC".
        first = bank_rows.iloc[0]
        counterparty = names_by_upper[first["description"].split(" ", 2)[2]]
        currency = "USD"
        event_date = first["value_date"]

    if currency != "USD":
        # A foreign bill is issued in its own currency.
        doc_amount = ledger_rows.iloc[0]["foreign_amount"]
    elif len(bank_rows):
        doc_amount = bank_rows.iloc[0]["amount"]
    else:
        doc_amount = ledger_rows.iloc[0]["amount"]

    return {
        "reference": reference,
        "counterparty": counterparty,
        "currency": currency,
        "doc_amount": doc_amount,
        # Invoices are issued a few weeks before they are paid.
        "issue_date": event_date - timedelta(days=rng.randint(20, 40)),
    }


# ---------------------------------------------------------------------------
# Main entry point for this module
# ---------------------------------------------------------------------------
def generate_documents(bank: pd.DataFrame, ledger: pd.DataFrame,
                       counterparties: list[str], rng: random.Random) -> list[str]:
    """Build every supporting document and return their texts (shuffled).

    `bank` and `ledger` must still have their private exception columns —
    we use them to decide which references need documents.
    """
    names_by_upper = {name.upper(): name for name in counterparties}
    documents = [fee_schedule()]

    # --- Invoices and bills: every exception reference, plus some noise -----
    # sorted() matters here: Python's set ordering can change between runs,
    # and we need the exact same output every time.
    tagged = pd.concat([bank, ledger])
    exception_refs = sorted(
        {r for r in tagged.loc[tagged["exception_id"].notna(), "reference"] if r}
    )
    normal_refs = sorted(
        {r for r in ledger["reference"] if not r.startswith("PAY")} - set(exception_refs)
    )
    noise_refs = rng.sample(normal_refs, N_NOISE_REFERENCES)

    for reference in exception_refs + noise_refs:
        facts = reference_facts(reference, bank, ledger, names_by_upper, rng)
        documents.append(invoice_or_bill(facts))

    # --- Wire confirmations for every international wire ---------------------
    wires = bank[bank["description"].str.startswith("INTL WIRE OUT")]
    wires = wires.sort_values(["value_date", "bank_txn_id"])
    for position, (_, wire) in enumerate(wires.iterrows()):
        ledger_row = ledger[ledger["reference"] == wire["reference"]].iloc[0]
        # Matches the fee schedule: the first wire of the month is free.
        documents.append(wire_confirmation(wire, ledger_row, fee_charged=position > 0))

    # --- Month-end payments still in transit ----------------------------------
    in_transit = ledger[ledger["exception_type"] == "timing_difference"]
    for _, row in in_transit.iterrows():
        if row["amount"] > 0:
            documents.append(customer_remittance(row))
        else:
            documents.append(ap_payment_run(row))

    # Shuffle so that document numbers don't reveal which ones matter.
    rng.shuffle(documents)
    return documents


def write_documents(documents: list[str]) -> None:
    """Write each document to data/raw/documents/DOC-001.txt, DOC-002.txt, ...

    Old documents are deleted first, so a previous run with different
    settings can't leave stale files behind.
    """
    folder = settings.documents_dir
    folder.mkdir(parents=True, exist_ok=True)
    for old_file in folder.glob("DOC-*.txt"):
        old_file.unlink()

    for number, text in enumerate(documents, start=1):
        (folder / f"DOC-{number:03d}.txt").write_text(text + "\n")
