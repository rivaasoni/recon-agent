-- ---------------------------------------------------------------------------
-- metrics_resolution_status
--
-- GRAIN: one row per review status (no_proposal / pending / approved / rejected).
--
-- The review queue at a glance: how many cases sit at each stage and how
-- much money they represent. 'no_proposal' is listed separately from
-- 'pending' on purpose: one is waiting for a human, the other is waiting
-- for someone to notice the agent produced nothing.
-- ---------------------------------------------------------------------------

with cases as (

    select review_status, break_value, cost_usd
    from {{ ref('fct_exception_cases') }}

),

totals as (

    select count(*) as all_cases from cases

)

select
    cases.review_status,
    count(*)                                        as cases,
    count(*) / nullif(totals.all_cases, 0)::double  as share_of_cases,
    sum(cases.break_value)                          as break_value,
    sum(cases.cost_usd)                             as agent_cost_usd

from cases
cross join totals
group by cases.review_status, totals.all_cases
order by cases desc
