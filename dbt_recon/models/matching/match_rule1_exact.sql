-- ---------------------------------------------------------------------------
-- match_rule1_exact
--
-- Rule 1: a bank row and a ledger row match when ALL of these hold:
--   - same reference            (e.g. both say INV-1021)
--   - same amount, to the cent
--   - dates within the window   (var: match_date_window_days)
--
-- Every row may be matched AT MOST ONCE (one-to-one). When several rows
-- qualify — e.g. the same bill posted twice in the ledger — the EARLIEST
-- posting wins (first-in, first-out) and the later one is left unmatched,
-- so it surfaces as an exception instead of being silently hidden.
--
-- Output: one row per matched pair.
-- ---------------------------------------------------------------------------

with bank as (

    -- Rows with no reference (e.g. bank fees) can't match on reference.
    select * from {{ ref('bank_transactions') }}
    where reference is not null

),

ledger as (

    select * from {{ ref('gl_entries') }}
    where reference is not null

),

-- Step A: every pair that satisfies the rule. This CAN contain one bank row
-- paired with two ledger rows — step B fixes that.
candidates as (

    select
        bank.bank_txn_id,
        ledger.gl_entry_id,
        bank.reference,
        bank.amount,
        ledger.posting_date,
        bank.value_date,
        -- Positive = bank cleared AFTER the ledger posting (the usual case).
        date_diff('day', ledger.posting_date, bank.value_date) as days_to_clear

    from bank
    inner join ledger
        on  bank.reference = ledger.reference
        and bank.amount    = ledger.amount
        and abs(date_diff('day', ledger.posting_date, bank.value_date))
            <= {{ var('match_date_window_days') }}

),

-- Step B: rank each side's options, earliest first (FIFO).
--   bank_rank = 1 -> this is the bank row's favourite ledger row
--   ledger_rank = 1 -> this is the ledger row's favourite bank row
-- ID is the tie-breaker, so the result is identical on every run.
ranked as (

    select
        *,
        row_number() over (
            partition by bank_txn_id
            order by posting_date, gl_entry_id
        ) as bank_rank,
        row_number() over (
            partition by gl_entry_id
            order by value_date, bank_txn_id
        ) as ledger_rank

    from candidates

)

-- Keep a pair only when BOTH sides pick each other. Anything left over is
-- NOT matched here and will show up in the exceptions table (Step 3).
select
    bank_txn_id,
    gl_entry_id,
    'R1_exact' as match_rule,
    reference,
    amount,
    posting_date,
    value_date,
    days_to_clear

from ranked
where bank_rank = 1
  and ledger_rank = 1
