"""
Synthetic data generator — Phase 2.

What this produces
------------------
Three files describing ONE fictional month of cash activity:

    data/raw/bank_statement.csv   what the BANK says happened
    data/raw/general_ledger.csv   what OUR ACCOUNTANTS recorded
    data/eval/answer_key.csv      the truth about every seeded exception (hidden from the agent)

plus supporting documents in data/raw/documents/ (see documents.py).

Reconciliation is the job of proving the first two agree. We build it in three
stages:

  1. generate_baseline()  — a month where bank and ledger agree perfectly.
  2. seed_exceptions()    — deliberately break some rows in six known ways,
                            and tag each broken row so we know the truth.
  3. build_answer_key()   — save that truth to data/eval/answer_key.csv,
                            for grading the agent in Phase 8.

ALL DATA IS SYNTHETIC. Counterparty names come from Faker and are invented.
Exchange rates are illustrative numbers, not market data.

Run it:
    python -m recon.data_gen.generate
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from faker import Faker

from recon.config import settings
from recon.data_gen.documents import generate_documents, write_documents

# ---------------------------------------------------------------------------
# Knobs you can turn
# ---------------------------------------------------------------------------
MONTH_START = date(2026, 8, 1)
MONTH_END = date(2026, 8, 31)

N_CUSTOMER_RECEIPTS = 60   # money coming IN  (customers paying our invoices)
N_VENDOR_PAYMENTS = 55     # money going OUT  (us paying suppliers' bills)
N_COUNTERPARTIES = 15      # how many distinct customers / vendors to invent

# The ledger account every row belongs to. A real ledger has hundreds of
# accounts; for a bank rec we only care about the one that mirrors the bank.
CASH_ACCOUNT = "1000 Cash - Operating"

# Rate our accountants use when they BOOK a foreign-currency bill.
# Invented, round numbers — this is synthetic data, not market data.
BOOKING_RATES = {"EUR": 1.10, "GBP": 1.28}

# Columns that exist only inside this script. They are our private "ground
# truth" and are dropped before the CSVs are written.
PRIVATE_COLUMNS = ["event_id", "exception_id", "exception_type"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def business_days(start: date, end: date) -> list[date]:
    """Every Monday–Friday between start and end, inclusive.

    Banks do not post transactions on weekends, so our data shouldn't either.
    (We ignore public holidays to keep things simple.)
    """
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # 0 = Monday ... 4 = Friday
            days.append(current)
        current += timedelta(days=1)
    return days


def add_business_days(start: date, n: int) -> date:
    """Move forward n business days, skipping weekends."""
    current = start
    while n > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            n -= 1
    return current


def random_amount(rng: random.Random, low: int, high: int) -> float:
    """A random dollar amount between low and high, with cents.

    We pick a whole number of CENTS and divide by 100. Picking a float directly
    (e.g. rng.uniform) gives values like 1234.5678901 that no bank would show.
    """
    cents = rng.randint(low * 100, high * 100)
    return cents / 100


def transpose_digits(amount: float, rng: random.Random) -> float:
    """Simulate a typo where two neighbouring digits get swapped.

    Example: 4,572.10 -> 4,752.10. The difference between the original and
    the typo is always divisible by 9 — a classic accountant's clue.
    """
    digits = list(f"{abs(amount):.2f}".replace(".", ""))  # "4572.10" -> "457210"

    # Only swap positions where the two digits differ (otherwise nothing
    # changes) and where the swap wouldn't put a 0 at the front.
    options = [
        i for i in range(len(digits) - 1)
        if digits[i] != digits[i + 1] and not (i == 0 and digits[1] == "0")
    ]
    i = rng.choice(options)
    digits[i], digits[i + 1] = digits[i + 1], digits[i]

    typo = int("".join(digits)) / 100
    return typo if amount > 0 else -typo


# ---------------------------------------------------------------------------
# A container for the month we are building
# ---------------------------------------------------------------------------
@dataclass
class Month:
    """Holds the bank and ledger rows while we build them.

    Rows are plain dicts in lists. We only turn them into DataFrames at the
    very end, which keeps adding and editing rows simple.
    """

    customers: list[str]
    vendors: list[str]
    ledger_days: list[date]  # business days where a ledger entry may be dated
    bank_rows: list[dict] = field(default_factory=list)
    ledger_rows: list[dict] = field(default_factory=list)
    _last_event: int = 0
    _last_exception: int = 0

    def new_event_id(self) -> int:
        """A new number linking a bank row to its ledger row (private)."""
        self._last_event += 1
        return self._last_event

    def new_exception_id(self) -> str:
        """A new exception label: EXC-01, EXC-02, ..."""
        self._last_exception += 1
        return f"EXC-{self._last_exception:02d}"

    def add_bank(self, event_id, value_date, description, reference, amount) -> dict:
        row = {
            "event_id": event_id,
            "value_date": value_date,
            "description": description,
            "reference": reference,
            "amount": amount,
            "exception_id": None,
            "exception_type": None,
        }
        self.bank_rows.append(row)
        return row

    def add_ledger(self, event_id, posting_date, counterparty, description, reference,
                   amount, currency="USD", foreign_amount=None, fx_rate=None) -> dict:
        row = {
            "event_id": event_id,
            "posting_date": posting_date,
            "account": CASH_ACCOUNT,
            "counterparty": counterparty,
            "description": description,
            "reference": reference,
            "amount": amount,              # always in USD, our home currency
            "currency": currency,          # currency of the underlying invoice
            "foreign_amount": foreign_amount,  # invoice amount in that currency
            "fx_rate": fx_rate,            # rate used to convert it to USD
            "exception_id": None,
            "exception_type": None,
        }
        self.ledger_rows.append(row)
        return row

    def bank_row_for(self, event_id: int) -> dict:
        """Find the bank row belonging to a given event."""
        return next(r for r in self.bank_rows if r["event_id"] == event_id)


def tag(row: dict, exception_id: str, exception_type: str) -> None:
    """Mark a row as part of a seeded exception (private ground truth)."""
    row["exception_id"] = exception_id
    row["exception_type"] = exception_type


# ---------------------------------------------------------------------------
# Stage 1: the baseline month (everything matches)
# ---------------------------------------------------------------------------
def generate_baseline(rng: random.Random, fake: Faker) -> Month:
    """Build a month where the bank and the ledger agree perfectly.

    Each business EVENT (e.g. "Customer X paid invoice INV-1004") produces:
      - one ledger row, dated when our accountant recorded it, and
      - one bank row, dated when the money actually cleared (0–2 business
        days later — that small lag is normal and NOT an exception).
    """
    days = business_days(MONTH_START, MONTH_END)
    month = Month(
        customers=[fake.unique.company() for _ in range(N_COUNTERPARTIES)],
        vendors=[fake.unique.company() for _ in range(N_COUNTERPARTIES)],
        # Leave the last 2 business days out, so a 2-day clearing lag still
        # lands inside the month. Cross-month lag is a real exception (below).
        ledger_days=days[:-2],
    )

    def add_matched_event(counterparty, ledger_date, amount, reference, bank_text, ledger_text,
                          max_lag=2):
        """max_lag = the most business days the bank may take to clear it."""
        event_id = month.new_event_id()
        bank_date = add_business_days(ledger_date, rng.randint(0, max_lag))
        month.add_bank(event_id, bank_date, bank_text, reference, amount)
        month.add_ledger(event_id, ledger_date, counterparty, ledger_text, reference, amount)

    # Money IN: customers paying our invoices. Positive amounts.
    for i in range(N_CUSTOMER_RECEIPTS):
        name = rng.choice(month.customers)
        ref = f"INV-{1001 + i}"
        add_matched_event(
            counterparty=name,
            ledger_date=rng.choice(month.ledger_days),
            amount=random_amount(rng, 500, 25_000),
            reference=ref,
            # Banks describe things tersely and in capitals; accountants write
            # fuller descriptions. Real recs have to live with that mismatch.
            bank_text=f"ACH CREDIT {name.upper()}",
            ledger_text=f"Customer payment - {name} - {ref}",
        )

    # Money OUT: us paying suppliers. Negative amounts.
    for i in range(N_VENDOR_PAYMENTS):
        name = rng.choice(month.vendors)
        ref = f"BILL-{5001 + i}"
        add_matched_event(
            counterparty=name,
            ledger_date=rng.choice(month.ledger_days),
            amount=-random_amount(rng, 100, 15_000),
            reference=ref,
            bank_text=f"ACH DEBIT {name.upper()}",
            ledger_text=f"Vendor payment - {name} - {ref}",
        )

    # Payroll: two large, predictable outflows every month.
    for pay_day, label in ((date(2026, 8, 14), "A"), (date(2026, 8, 28), "B")):
        ref = f"PAY-2026-08-{label}"
        add_matched_event(
            counterparty="Payroll",
            ledger_date=pay_day,
            amount=-random_amount(rng, 40_000, 55_000),
            reference=ref,
            bank_text=f"PAYROLL BATCH {ref}",
            ledger_text=f"Payroll run {label} - August 2026",
            # Payroll clears ON the pay date — employees must be paid that day.
            # (With a lag, run B on Fri 28 Aug could land on Tue 1 Sep, putting
            # a September row on an August statement. A test caught this.)
            max_lag=0,
        )

    return month


# ---------------------------------------------------------------------------
# Stage 2: seed exceptions — one function per exception type
# ---------------------------------------------------------------------------
def seed_duplicates(month: Month, rng: random.Random, originals: list[dict]) -> None:
    """An accountant posts the same bill twice.

    The ORIGINAL still matches the bank. Only the extra copy is the exception.
    """
    for original in originals:
        copy = dict(original)  # dict() makes a separate copy, not a reference
        copy["posting_date"] = add_business_days(original["posting_date"], rng.randint(0, 1))
        tag(copy, month.new_exception_id(), "duplicate")
        month.ledger_rows.append(copy)


def seed_amount_mismatches(month: Month, rng: random.Random, targets: list[dict]) -> None:
    """The accountant typed the amount wrong (swapped two digits).

    The bank has the true amount; the ledger has the typo. Both rows are
    part of the exception, because neither will match the other on amount.
    """
    for ledger_row in targets:
        ledger_row["amount"] = transpose_digits(ledger_row["amount"], rng)
        exception_id = month.new_exception_id()
        tag(ledger_row, exception_id, "amount_mismatch")
        tag(month.bank_row_for(ledger_row["event_id"]), exception_id, "amount_mismatch")


def seed_timing_differences(month: Month, rng: random.Random) -> None:
    """Booked in the ledger at month-end, but clears at the bank in September.

    Accountants call these "deposits in transit" (money in) and "outstanding
    payments" (money out). They fix themselves next month — the right action
    is usually to wait, NOT to post a correcting entry.
    """
    cases = [
        # (posting date,     counterparty,              amount,                        reference,  kind)
        (date(2026, 8, 31), rng.choice(month.customers), random_amount(rng, 1_000, 20_000), "INV-1061", "Customer payment"),
        (date(2026, 8, 31), rng.choice(month.customers), random_amount(rng, 1_000, 20_000), "INV-1062", "Customer payment"),
        (date(2026, 8, 28), rng.choice(month.vendors), -random_amount(rng, 1_000, 10_000), "BILL-5056", "Vendor payment"),
    ]
    for posting_date, name, amount, ref, kind in cases:
        row = month.add_ledger(month.new_event_id(), posting_date, name, f"{kind} - {name} - {ref}", ref, amount)
        tag(row, month.new_exception_id(), "timing_difference")
        # Deliberately NO bank row: the money clears after this statement ends.


def seed_missing_ledger_entries(month: Month, rng: random.Random) -> None:
    """Money moved at the bank, but nobody recorded it in the ledger."""
    customer = rng.choice(month.customers)
    vendor = rng.choice(month.vendors)
    cases = [
        (f"ACH CREDIT {customer.upper()}", "INV-1063", random_amount(rng, 1_000, 15_000)),
        (f"ACH DEBIT {vendor.upper()}", "BILL-5057", -random_amount(rng, 500, 8_000)),
    ]
    for bank_text, ref, amount in cases:
        row = month.add_bank(month.new_event_id(), rng.choice(month.ledger_days), bank_text, ref, amount)
        tag(row, month.new_exception_id(), "missing_ledger_entry")
        # Deliberately NO ledger row.


def seed_fx_differences(month: Month, rng: random.Random) -> list[date]:
    """A foreign-currency bill is booked at one rate but paid at another.

    Our ledger converts the invoice to USD using the BOOKING rate. By the time
    the bank wires the money, the rate has moved a little, so the USD amount
    leaving the bank is slightly different. The foreign amount is identical.

    Returns the wire dates, so bank_fees can charge a wire fee on those days.
    """
    wire_dates = []
    for i, currency in enumerate(["EUR", "GBP", "EUR"]):
        name = rng.choice(month.vendors)
        ref = f"BILL-{5058 + i}"
        foreign_amount = random_amount(rng, 3_000, 20_000)
        booking_rate = BOOKING_RATES[currency]

        # The rate drifts 0.5%–2% up or down between booking and payment.
        drift = rng.uniform(0.005, 0.02) * rng.choice([1, -1])
        settlement_rate = round(booking_rate * (1 + drift), 4)

        ledger_date = rng.choice(month.ledger_days)
        bank_date = add_business_days(ledger_date, rng.randint(0, 1))
        wire_dates.append(bank_date)

        event_id = month.new_event_id()
        exception_id = month.new_exception_id()
        ledger_row = month.add_ledger(
            event_id, ledger_date, name,
            f"Vendor payment - {name} - {ref} ({currency} {foreign_amount:,.2f} @ {booking_rate:.4f})",
            ref,
            amount=-round(foreign_amount * booking_rate, 2),
            currency=currency,
            foreign_amount=foreign_amount,
            fx_rate=booking_rate,
        )
        bank_row = month.add_bank(
            event_id, bank_date,
            f"INTL WIRE OUT {name.upper()} {currency} {foreign_amount:,.2f} @{settlement_rate:.4f}",
            ref,
            amount=-round(foreign_amount * settlement_rate, 2),
        )
        tag(ledger_row, exception_id, "fx_difference")
        tag(bank_row, exception_id, "fx_difference")
    return wire_dates


def seed_bank_fees(month: Month, wire_dates: list[date]) -> None:
    """The bank charges fees that nobody has booked in the ledger yet."""
    fees = [(date(2026, 8, 31), "MONTHLY ACCOUNT SERVICE CHARGE", -45.00)]
    # The bank's fee schedule (see documents.py): the FIRST international wire
    # each month is free, every later one costs $35.
    fees += [(d, "INTL WIRE TRANSFER FEE", -35.00) for d in sorted(wire_dates)[1:]]

    for value_date, bank_text, amount in fees:
        # Fees have no invoice or bill, so the reference is blank.
        row = month.add_bank(month.new_event_id(), value_date, bank_text, "", amount)
        tag(row, month.new_exception_id(), "bank_fee")


def seed_exceptions(month: Month, rng: random.Random) -> None:
    """Break the perfect month in six known ways."""
    # Pick 5 ordinary baseline entries to damage: 2 get duplicated, 3 get a
    # typo. We pick them all at once with rng.sample so no entry is chosen
    # twice. Payroll is excluded to keep things simple.
    candidates = [r for r in month.ledger_rows if r["counterparty"] != "Payroll"]
    chosen = rng.sample(candidates, 5)

    seed_duplicates(month, rng, chosen[:2])
    seed_amount_mismatches(month, rng, chosen[2:])
    seed_timing_differences(month, rng)
    seed_missing_ledger_entries(month, rng)
    wire_dates = seed_fx_differences(month, rng)
    seed_bank_fees(month, wire_dates)


# ---------------------------------------------------------------------------
# Turn the rows into DataFrames with public IDs
# ---------------------------------------------------------------------------
def to_dataframes(month: Month) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert the rows to DataFrames and give each file its own IDs.

    IDs are numbered in date order, separately per file. If we reused
    event_id, row 17 in the bank would always pair with row 17 in the
    ledger — which would leak the answer to the matching step in Phase 4.
    """
    bank = pd.DataFrame(month.bank_rows)
    bank = bank.sort_values(["value_date", "event_id"], kind="stable").reset_index(drop=True)
    bank.insert(0, "bank_txn_id", [f"BNK-{n:04d}" for n in range(1, len(bank) + 1)])

    ledger = pd.DataFrame(month.ledger_rows)
    ledger = ledger.sort_values(["posting_date", "event_id"], kind="stable").reset_index(drop=True)
    ledger.insert(0, "gl_entry_id", [f"GL-{n:04d}" for n in range(1, len(ledger) + 1)])

    return bank, ledger


# ---------------------------------------------------------------------------
# Stage 3: the answer key (ground truth for grading the agent in Phase 8)
# ---------------------------------------------------------------------------
# Ledger accounts used on the "other side" of a correcting journal entry.
# Every entry touches Cash plus one of these.
FEES_ACCOUNT = "6100 Bank Fees"
FX_ACCOUNT = "7100 FX Gain/Loss"


def subledger_account(amount: float) -> str:
    """Money IN relates to a customer (receivables); money OUT to a vendor (payables)."""
    return "1200 Accounts Receivable" if amount > 0 else "2000 Accounts Payable"


def describe_fix(exception_type, reference, bank_amount, ledger_amount) -> dict:
    """What a good accountant would do about one exception.

    cash_adjustment = how much the ledger's Cash balance must change so it
    agrees with the bank. Positive = increase cash, negative = decrease.
    """
    if exception_type == "timing_difference":
        return {
            "expected_action": "no_entry",
            "cash_adjustment": 0.0,
            "offset_account": "",
            "explanation": f"{reference} was booked at month-end but had not cleared the bank "
                           "by 31 Aug. It should clear in early September; no entry is needed.",
        }
    if exception_type == "duplicate":
        return {
            "expected_action": "reverse_duplicate",
            "cash_adjustment": -ledger_amount,
            "offset_account": subledger_account(ledger_amount),
            "explanation": f"{reference} was posted to the ledger twice but paid once. "
                           "Reverse the duplicate entry.",
        }
    if exception_type == "bank_fee":
        return {
            "expected_action": "book_bank_fee",
            "cash_adjustment": bank_amount,
            "offset_account": FEES_ACCOUNT,
            "explanation": f"The bank charged a {abs(bank_amount):,.2f} fee that is not in "
                           "the ledger. Book it to bank fees expense.",
        }
    if exception_type == "fx_difference":
        diff = round(bank_amount - ledger_amount, 2)
        gain_or_loss = "loss" if diff < 0 else "gain"
        return {
            "expected_action": "book_fx_gain_loss",
            "cash_adjustment": diff,
            "offset_account": FX_ACCOUNT,
            "explanation": f"{reference} was booked at the invoice-date rate but settled at a "
                           f"different rate. Book the {abs(diff):,.2f} difference as an FX {gain_or_loss}.",
        }
    if exception_type == "missing_ledger_entry":
        return {
            "expected_action": "book_missing_entry",
            "cash_adjustment": bank_amount,
            "offset_account": subledger_account(bank_amount),
            "explanation": f"{reference} cleared the bank but was never recorded in the ledger. "
                           "Record the transaction.",
        }
    if exception_type == "amount_mismatch":
        diff = round(bank_amount - ledger_amount, 2)
        return {
            "expected_action": "correct_amount",
            "cash_adjustment": diff,
            "offset_account": subledger_account(bank_amount),
            "explanation": f"{reference} was keyed as {ledger_amount:,.2f} instead of "
                           f"{bank_amount:,.2f} — two digits transposed (the difference, "
                           f"{abs(diff):,.2f}, is divisible by 9). Correct the ledger amount.",
        }
    raise ValueError(f"Unknown exception type: {exception_type}")


def build_answer_key(bank: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    """One row per seeded exception: the rows involved, the type, and the fix."""
    exception_ids = sorted(
        set(bank["exception_id"].dropna()) | set(ledger["exception_id"].dropna())
    )

    key_rows = []
    for exception_id in exception_ids:
        bank_part = bank[bank["exception_id"] == exception_id]
        ledger_part = ledger[ledger["exception_id"] == exception_id]
        both = pd.concat([bank_part, ledger_part])

        exception_type = both["exception_type"].iloc[0]
        # Bank fees have a blank reference, so fall back to "(none)".
        references = [r for r in both["reference"] if r]
        reference = references[0] if references else "(none)"
        # None means "this side has no row for this exception".
        bank_amount = round(bank_part["amount"].sum(), 2) if len(bank_part) else None
        ledger_amount = round(ledger_part["amount"].sum(), 2) if len(ledger_part) else None

        fix = describe_fix(exception_type, reference, bank_amount, ledger_amount)
        key_rows.append({
            "exception_id": exception_id,
            "exception_type": exception_type,
            "bank_txn_ids": ", ".join(bank_part["bank_txn_id"]),
            "gl_entry_ids": ", ".join(ledger_part["gl_entry_id"]),
            "reference": reference,
            "bank_amount": bank_amount,
            "ledger_amount": ledger_amount,
            **fix,  # expected_action, cash_adjustment, offset_account, explanation
        })

    key = pd.DataFrame(key_rows)
    key["cash_adjustment"] = key["cash_adjustment"].round(2)
    return key


def check_answer_key(bank: pd.DataFrame, ledger: pd.DataFrame, key: pd.DataFrame) -> None:
    """Prove the answer key fully explains the gap between bank and ledger.

    After booking every adjustment, the only remaining gap should be the
    timing items that are in the ledger but haven't reached the bank yet:

        bank - ledger  ==  sum(adjustments) - (timing items)

    If a seeded exception were missing from the key, or had the wrong
    adjustment, this would not balance — so we stop loudly instead of
    quietly writing a wrong answer key.
    """
    actual_gap = round(bank["amount"].sum() - ledger["amount"].sum(), 2)
    timing_total = ledger.loc[ledger["exception_type"] == "timing_difference", "amount"].sum()
    explained_gap = round(key["cash_adjustment"].sum() - timing_total, 2)

    if actual_gap != explained_gap:
        raise RuntimeError(
            f"Answer key does not balance: actual gap {actual_gap:,.2f} "
            f"vs explained gap {explained_gap:,.2f}"
        )
    print(f"Reconciliation proof: gap of {actual_gap:,.2f} fully explained by the answer key.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def build_dataset(seed: int) -> tuple[Month, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run stages 1–3 entirely in memory — no files are written.

    Returns (month, bank, ledger, answer_key). bank and ledger still contain
    the private ground-truth columns. Tests call this directly.
    """
    # Seed BOTH sources of randomness so every run produces identical data.
    rng = random.Random(seed)
    Faker.seed(seed)
    fake = Faker("en_US")

    month = generate_baseline(rng, fake)
    seed_exceptions(month, rng)
    bank, ledger = to_dataframes(month)

    key = build_answer_key(bank, ledger)
    check_answer_key(bank, ledger, key)
    return month, bank, ledger, key


def build_documents(month: Month, bank: pd.DataFrame, ledger: pd.DataFrame, seed: int) -> list[str]:
    """Supporting documents, from their OWN random stream.

    A separate random.Random means that adding a new document type later can
    never shift the random numbers used for the bank and ledger data.
    """
    return generate_documents(bank, ledger, month.customers + month.vendors, random.Random(seed))


def main() -> None:
    month, bank, ledger, key = build_dataset(settings.random_seed)

    settings.ensure_dirs()
    bank_path = settings.raw_dir / "bank_statement.csv"
    ledger_path = settings.raw_dir / "general_ledger.csv"
    # Drop the private ground-truth columns before writing.
    bank.drop(columns=PRIVATE_COLUMNS).to_csv(bank_path, index=False)
    ledger.drop(columns=PRIVATE_COLUMNS).to_csv(ledger_path, index=False)

    print(f"Wrote {len(bank):>4} rows -> {bank_path.relative_to(settings.project_root)}")
    print(f"Wrote {len(ledger):>4} rows -> {ledger_path.relative_to(settings.project_root)}")
    print(f"Bank total:   {bank['amount'].sum():>14,.2f}")
    print(f"Ledger total: {ledger['amount'].sum():>14,.2f}")
    print(f"Difference:   {bank['amount'].sum() - ledger['amount'].sum():>14,.2f}  <- the exceptions explain this")

    # The answer key goes in data/eval/, NOT data/raw/, so it can never be
    # loaded into the warehouse that the agent queries.
    key_path = settings.eval_dir / "answer_key.csv"
    key.to_csv(key_path, index=False)
    print(f"Wrote {len(key):>4} rows -> {key_path.relative_to(settings.project_root)}")

    documents = build_documents(month, bank, ledger, settings.random_seed)
    write_documents(documents)
    docs_folder = settings.documents_dir.relative_to(settings.project_root)
    print(f"Wrote {len(documents):>4} docs -> {docs_folder}/")

    print("\nSeeded exceptions by type:")
    print(key["exception_type"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
