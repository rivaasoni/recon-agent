-- ---------------------------------------------------------------------------
-- metrics_agent_runs
--
-- GRAIN: one row per agent run.
--
-- What each run cost and how reliable it was. Comparing runs is how you
-- answer "did that prompt change help?" or "is the cheaper model good
-- enough?" — alongside the accuracy numbers from the Phase 8 eval report.
-- ---------------------------------------------------------------------------

with runs as (

    select * from {{ ref('stg_agent_case_runs') }}

)

select
    run_id,
    min(model_requested)                                        as model_requested,
    min(started_at)                                             as started_at,
    count(*)                                                    as cases,

    count(*) filter (where status = 'completed')                as completed_cases,
    count(*) filter (where status <> 'completed')               as failed_cases,
    count(*) filter (where status = 'completed')
        / nullif(count(*), 0)::double                           as completion_rate,

    sum(cost_usd)                                               as cost_usd,
    avg(cost_usd)                                               as cost_per_case_usd,
    max(cost_usd)                                               as max_case_cost_usd,

    sum(latency_seconds)                                        as total_seconds,
    avg(latency_seconds)                                        as avg_seconds_per_case,
    median(latency_seconds)                                     as median_seconds_per_case,

    sum(input_tokens)                                           as input_tokens,
    sum(output_tokens)                                          as output_tokens,
    sum(steps)                                                  as steps,
    sum(tool_calls)                                             as tool_calls,
    sum(tool_errors)                                            as tool_errors

from runs
group by run_id
order by started_at
