-- ---------------------------------------------------------------------------
-- gl_entries  (cleaned layer)
--
-- Business-ready general ledger entries for the cash account.
-- ---------------------------------------------------------------------------

with staged as (

    select * from {{ ref('stg_gl_entries') }}

)

select
    gl_entry_id,
    posting_date,
    account,
    counterparty,
    description,
    reference,
    amount,
    abs(amount) as abs_amount,

    case
        when amount > 0 then 'inflow'
        when amount < 0 then 'outflow'
        else 'zero'
    end as direction,

    currency,
    foreign_amount,
    fx_rate,
    -- A quick flag for the agent: foreign-currency entries are where FX
    -- differences can happen.
    currency <> 'USD' as is_foreign_currency,

    _source_file,
    _loaded_at

from staged
