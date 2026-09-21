-- ---------------------------------------------------------------------------
-- Singular test: the pipeline must not gain, lose or change any money.
--
-- How singular tests work: this query returns the BAD rows. dbt passes the
-- test if it returns zero rows, and fails it otherwise.
--
-- We compare row counts and totals between the raw tables (text, as loaded)
-- and the cleaned tables (typed, transformed). Any difference means a
-- transformation dropped, duplicated or altered rows — which would make
-- every later reconciliation result wrong.
-- ---------------------------------------------------------------------------

with comparison as (

    select
        'bank' as side,
        (select count(*) from {{ source('raw', 'bank_statement') }})                          as raw_rows,
        (select count(*) from {{ ref('bank_transactions') }})                                 as cleaned_rows,
        (select sum(cast(amount as decimal(12, 2))) from {{ source('raw', 'bank_statement') }}) as raw_total,
        (select sum(amount) from {{ ref('bank_transactions') }})                              as cleaned_total

    union all

    select
        'ledger',
        (select count(*) from {{ source('raw', 'general_ledger') }}),
        (select count(*) from {{ ref('gl_entries') }}),
        (select sum(cast(amount as decimal(12, 2))) from {{ source('raw', 'general_ledger') }}),
        (select sum(amount) from {{ ref('gl_entries') }})

)

select *
from comparison
where raw_rows <> cleaned_rows
   or raw_total <> cleaned_total
