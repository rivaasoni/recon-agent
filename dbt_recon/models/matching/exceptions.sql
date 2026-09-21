-- ---------------------------------------------------------------------------
-- exceptions
--
-- Everything Rule 1 could NOT match, grouped into CASES for the agent.
--
--   both_sides  : an unmatched bank row AND an unmatched ledger row share a
--                 reference — same transaction, but something differs.
--   bank_only   : money moved at the bank; nothing in the ledger pairs with it.
--   ledger_only : booked in the ledger; nothing at the bank pairs with it.
--
-- This table states FACTS (shape, amounts, difference, whether the reference
-- was matched elsewhere). It never says what TYPE of exception a case is —
-- deciding that is the agent's job, and what Phase 8 grades.
-- ---------------------------------------------------------------------------

with bank as (

    select * from {{ ref('bank_transactions') }}

),

ledger as (

    select * from {{ ref('gl_entries') }}

),

matches as (

    select * from {{ ref('match_rule1_exact') }}

),

-- Anti-join: bank rows with NO partner in matches.
-- LEFT JOIN keeps every bank row; where no match attached, m.* is NULL.
unmatched_bank as (

    select bank.*
    from bank
    left join matches as m on bank.bank_txn_id = m.bank_txn_id
    where m.bank_txn_id is null

),

unmatched_ledger as (

    select ledger.*
    from ledger
    left join matches as m on ledger.gl_entry_id = m.gl_entry_id
    where m.gl_entry_id is null

),

-- Pair leftovers that share a reference. FULL OUTER JOIN keeps rows from
-- BOTH sides even when they have no partner. NULL references never equal
-- anything in SQL, so bank fees (no reference) always stay on their own.
cases as (

    select
        b.bank_txn_id,
        b.value_date        as bank_date,
        b.description       as bank_description,
        b.amount            as bank_amount,

        g.gl_entry_id,
        g.posting_date      as ledger_date,
        g.counterparty      as ledger_counterparty,
        g.description       as ledger_description,
        g.amount            as ledger_amount,
        g.currency          as ledger_currency,
        g.foreign_amount    as ledger_foreign_amount,
        g.fx_rate           as ledger_fx_rate,

        coalesce(b.reference, g.reference) as reference

    from unmatched_bank as b
    full outer join unmatched_ledger as g
        on b.reference = g.reference

)

select
    -- A readable, stable ID. 'CASE-' (not 'EXC-') so it can never be
    -- confused with the answer key's IDs.
    'CASE-' || lpad(
        cast(row_number() over (
            order by coalesce(bank_date, ledger_date), bank_txn_id, gl_entry_id
        ) as varchar),
        3, '0'
    ) as case_id,

    case
        when bank_txn_id is not null and gl_entry_id is not null then 'both_sides'
        when bank_txn_id is not null then 'bank_only'
        else 'ledger_only'
    end as case_shape,

    reference,
    coalesce(bank_date, ledger_date) as case_date,

    bank_txn_id,
    bank_date,
    bank_description,
    bank_amount,

    gl_entry_id,
    ledger_date,
    ledger_counterparty,
    ledger_description,
    ledger_amount,
    ledger_currency,
    ledger_foreign_amount,
    ledger_fx_rate,

    -- Only meaningful when both sides exist; NULL otherwise.
    bank_amount - ledger_amount as amount_difference,

    -- Has this same reference ALREADY been matched by Rule 1? A strong clue
    -- (e.g. a second posting of something that was already paid) — but a
    -- clue, not a verdict.
    -- coalesce(..., false): with no reference, `NULL in (...)` is NULL
    -- ("unknown"), not false. A flag should only ever be true or false.
    coalesce(reference in (select reference from matches), false) as reference_matched_elsewhere

from cases
