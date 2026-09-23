-- ---------------------------------------------------------------------------
-- metrics_exceptions_by_type
--
-- GRAIN: one row per exception type (as classified by the agent).
--
-- What kinds of breaks we get, what they're worth, how far through review
-- they are, and what the agent spent working them out.
--
-- Cases the agent never classified appear as 'unclassified' — they must not
-- vanish from a dashboard just because the agent produced nothing.
-- ---------------------------------------------------------------------------

with cases as (

    select
        coalesce(classification, 'unclassified') as exception_type,
        break_value,
        proposes_entry,
        review_status,
        is_open,
        cost_usd,
        steps,
        tool_calls
    from {{ ref('fct_exception_cases') }}

),

totals as (

    select count(*) as all_cases, sum(break_value) as all_value from cases

)

select
    cases.exception_type,
    count(*)                                                    as cases,
    sum(cases.break_value)                                      as break_value,
    avg(cases.break_value)                                      as avg_break_value,
    max(cases.break_value)                                      as largest_break_value,

    -- Share of the total, so a dashboard can rank types without re-deriving it.
    count(*) / nullif(totals.all_cases, 0)::double              as share_of_cases,
    sum(cases.break_value) / nullif(totals.all_value, 0)        as share_of_value,

    count(*) filter (where cases.proposes_entry)                as cases_needing_an_entry,
    count(*) filter (where cases.is_open)                       as open_cases,
    count(*) filter (where cases.review_status = 'approved')    as approved_cases,
    count(*) filter (where cases.review_status = 'rejected')    as rejected_cases,

    sum(cases.cost_usd)                                         as agent_cost_usd,
    avg(cases.steps)                                            as avg_steps,
    avg(cases.tool_calls)                                       as avg_tool_calls

from cases
cross join totals
group by cases.exception_type, totals.all_cases, totals.all_value
order by break_value desc
