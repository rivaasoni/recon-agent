-- ---------------------------------------------------------------------------
-- Singular test: every bank row and every ledger row must end up in EXACTLY
-- ONE place — either a Rule 1 match, or the exceptions table.
--
--   0 places  -> the row fell through the cracks; nobody will ever look at it
--   2+ places -> the row is double-counted (e.g. both matched AND an exception)
--
-- Returns the offending rows. Zero rows = pass.
-- ---------------------------------------------------------------------------

with placements as (

    -- Every place a bank row appears...
    select bank_txn_id as row_id, 'bank' as side from {{ ref('match_rule1_exact') }}
    union all
    select bank_txn_id, 'bank' from {{ ref('exceptions') }} where bank_txn_id is not null

    union all

    -- ...and every place a ledger row appears.
    select gl_entry_id, 'ledger' from {{ ref('match_rule1_exact') }}
    union all
    select gl_entry_id, 'ledger' from {{ ref('exceptions') }} where gl_entry_id is not null

),

all_rows as (

    select bank_txn_id as row_id, 'bank' as side from {{ ref('bank_transactions') }}
    union all
    select gl_entry_id, 'ledger' from {{ ref('gl_entries') }}

)

select
    all_rows.side,
    all_rows.row_id,
    count(placements.row_id) as times_placed

from all_rows
left join placements
    on  all_rows.row_id = placements.row_id
    and all_rows.side   = placements.side

group by all_rows.side, all_rows.row_id
having count(placements.row_id) <> 1
