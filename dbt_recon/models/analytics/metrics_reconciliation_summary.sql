-- ---------------------------------------------------------------------------
-- metrics_reconciliation_summary
--
-- GRAIN: one row per statement month.
--
-- The headline reconciliation numbers: how much matched automatically, what
-- was left as exceptions, and how much of that is still open.
--
-- Definitions (the point of this layer — one agreed meaning per metric):
--   bank_match_rate   = matched bank lines / all bank lines      (by COUNT)
--   value_match_rate  = matched bank value / all bank value      (by VALUE)
--   open_break_value  = break_value of cases with no human decision yet
--   resolution_rate   = decided cases / exception cases
-- ---------------------------------------------------------------------------

with bank as (

    select
        date_trunc('month', value_date)     as period,
        count(*)                            as bank_lines,
        sum(abs(amount))                    as bank_value
    from {{ ref('bank_transactions') }}
    group by 1

),

ledger as (

    select
        date_trunc('month', posting_date)   as period,
        count(*)                            as ledger_entries
    from {{ ref('gl_entries') }}
    group by 1

),

matched as (

    select
        date_trunc('month', value_date)     as period,
        count(*)                            as matched_pairs,
        sum(abs(amount))                    as matched_value
    from {{ ref('match_rule1_exact') }}
    group by 1

),

exception_cases as (

    select
        date_trunc('month', case_date)                          as period,
        count(*)                                                as exception_cases,
        sum(break_value)                                        as break_value,
        count(*) filter (where is_open)                         as open_cases,
        sum(break_value) filter (where is_open)                 as open_break_value,
        count(*) filter (where review_status = 'approved')      as approved_cases,
        count(*) filter (where review_status = 'rejected')      as rejected_cases,
        count(*) filter (where review_status = 'no_proposal')   as cases_without_proposal
    from {{ ref('fct_exception_cases') }}
    group by 1

)

select
    bank.period,
    bank.bank_lines,
    ledger.ledger_entries,
    matched.matched_pairs,

    -- nullif(x, 0) turns a divide-by-zero into NULL instead of an error.
    matched.matched_pairs / nullif(bank.bank_lines, 0)::double      as bank_match_rate,
    matched.matched_value / nullif(bank.bank_value, 0)              as value_match_rate,

    coalesce(exception_cases.exception_cases, 0)                    as exception_cases,
    coalesce(exception_cases.break_value, 0)                        as break_value,
    coalesce(exception_cases.open_cases, 0)                         as open_cases,
    coalesce(exception_cases.open_break_value, 0)                   as open_break_value,
    coalesce(exception_cases.approved_cases, 0)                     as approved_cases,
    coalesce(exception_cases.rejected_cases, 0)                     as rejected_cases,
    coalesce(exception_cases.cases_without_proposal, 0)             as cases_without_proposal,

    -- Share of exceptions a human has decided on (approved or rejected).
    (coalesce(exception_cases.approved_cases, 0) + coalesce(exception_cases.rejected_cases, 0))
        / nullif(exception_cases.exception_cases, 0)::double        as resolution_rate

from bank
left join ledger           on bank.period = ledger.period
left join matched          on bank.period = matched.period
left join exception_cases  on bank.period = exception_cases.period
order by bank.period
