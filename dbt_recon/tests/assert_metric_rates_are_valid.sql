-- ---------------------------------------------------------------------------
-- Singular test: every rate in the analytics layer must be a fraction
-- between 0 and 1, and no count may be negative.
--
-- Rates are computed with division, and division is where metrics go wrong:
-- a wrong denominator can quietly produce 4.7 (470%) or a negative share,
-- and a dashboard will happily display it.
--
-- Returns the offending rows. Zero rows = pass.
-- ---------------------------------------------------------------------------

with rates as (

    select 'bank_match_rate' as metric, bank_match_rate as value
    from {{ ref('metrics_reconciliation_summary') }}
    union all
    select 'value_match_rate', value_match_rate from {{ ref('metrics_reconciliation_summary') }}
    union all
    select 'resolution_rate', resolution_rate from {{ ref('metrics_reconciliation_summary') }}
    union all
    select 'share_of_cases', share_of_cases from {{ ref('metrics_exceptions_by_type') }}
    union all
    select 'share_of_value', share_of_value from {{ ref('metrics_exceptions_by_type') }}
    union all
    select 'share_of_cases', share_of_cases from {{ ref('metrics_resolution_status') }}
    union all
    select 'completion_rate', completion_rate from {{ ref('metrics_agent_runs') }}

),

counts as (

    select 'exception_cases' as metric, exception_cases as value
    from {{ ref('metrics_reconciliation_summary') }}
    union all
    select 'open_cases', open_cases from {{ ref('metrics_reconciliation_summary') }}
    union all
    select 'cases', cases from {{ ref('metrics_exceptions_by_type') }}
    union all
    select 'cases', cases from {{ ref('metrics_agent_runs') }}

)

-- A NULL rate is fine (no denominator yet); an out-of-range one is not.
select metric, value, 'rate outside 0-1' as problem
from rates
where value is not null and (value < 0 or value > 1)

union all

select metric, value, 'negative count' as problem
from counts
where value < 0
