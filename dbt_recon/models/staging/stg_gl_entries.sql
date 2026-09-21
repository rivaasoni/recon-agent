-- ---------------------------------------------------------------------------
-- stg_gl_entries
--
-- One row per general ledger entry in the cash account, with proper types.
-- Staging rules: rename, cast, standardize. No joins, no filters, no logic.
-- ---------------------------------------------------------------------------

with source as (

    select * from {{ source('raw', 'general_ledger') }}

),

cleaned as (

    select
        trim(gl_entry_id)                       as gl_entry_id,
        cast(posting_date as date)              as posting_date,
        trim(account)                           as account,
        trim(counterparty)                      as counterparty,
        trim(description)                       as description,
        nullif(trim(reference), '')             as reference,

        -- Always USD (our home currency), even for foreign-currency bills.
        cast(amount as decimal(12, 2))          as amount,

        -- Currency details. For USD entries foreign_amount and fx_rate are
        -- NULL — there is nothing to convert.
        upper(trim(currency))                   as currency,
        cast(foreign_amount as decimal(12, 2))  as foreign_amount,
        -- Exchange rates need more than 2 decimals: 4 is the market norm.
        cast(fx_rate as decimal(10, 4))         as fx_rate,

        _source_file,
        _loaded_at

    from source

)

select * from cleaned
