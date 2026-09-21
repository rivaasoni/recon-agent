-- ---------------------------------------------------------------------------
-- bank_transactions  (cleaned layer)
--
-- Business-ready bank statement lines. Adds the columns the matcher (Phase 4)
-- and the agent (Phase 6) need, on top of the typed staging model.
-- ---------------------------------------------------------------------------

with staged as (

    -- ref() reads another dbt model, and tells dbt to build that one first.
    select * from {{ ref('stg_bank_transactions') }}

)

select
    bank_txn_id,
    value_date,
    description,
    reference,
    amount,

    -- Matching compares sizes, so a positive copy of the amount is handy.
    abs(amount) as abs_amount,

    -- 'zero' should never happen; an accepted_values test will catch it.
    case
        when amount > 0 then 'inflow'
        when amount < 0 then 'outflow'
        else 'zero'
    end as direction,

    -- How the money moved, read from the bank's own description text.
    -- Anything we don't recognise becomes 'unknown', which a test rejects —
    -- so a new kind of bank line can't slip through silently.
    case
        when description like 'ACH CREDIT %'
          or description like 'ACH DEBIT %'     then 'ach'
        when description like 'INTL WIRE OUT %' then 'intl_wire'
        when description like 'PAYROLL BATCH %' then 'payroll'
        when description like '%FEE%'
          or description like '%SERVICE CHARGE%' then 'bank_charge'
        else 'unknown'
    end as channel,

    _source_file,
    _loaded_at

from staged
