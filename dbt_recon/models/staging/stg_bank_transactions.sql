-- ---------------------------------------------------------------------------
-- stg_bank_transactions
--
-- One row per bank statement line, with proper types.
-- Staging rules: rename, cast, standardize. No joins, no filters, no logic.
-- ---------------------------------------------------------------------------

with source as (

    -- Use the source function (not a hardcoded table name) so dbt tracks
    -- lineage. Careful: never write template braces inside a SQL comment —
    -- dbt's template engine runs them anyway, comment or not.
    select * from {{ source('raw', 'bank_statement') }}

),

cleaned as (

    select
        trim(bank_txn_id)                   as bank_txn_id,
        cast(value_date as date)            as value_date,
        trim(description)                   as description,
        -- One consistent "missing": empty or blank text becomes NULL.
        nullif(trim(reference), '')         as reference,
        -- DECIMAL, not DOUBLE: exact cents, no floating-point drift.
        cast(amount as decimal(12, 2))      as amount,

        -- Lineage columns carried through from the loader.
        _source_file,
        _loaded_at

    from source

)

select * from cleaned
