-- ---------------------------------------------------------------------------
-- stg_agent_case_runs
--
-- One row per CASE per RUN: how the agent's investigation of that case went.
--
-- The identity of a row is the PAIR (run_id, case_id) — the same case is
-- investigated again in every run. We build a surrogate key from the two so
-- a simple `unique` test can enforce that grain, and BI tools have a single
-- column to join on.
-- ---------------------------------------------------------------------------

with source as (

    select * from {{ source('raw', 'agent_case_runs') }}

)

select
    -- Surrogate key: 'run-20260921-215515:CASE-006'
    trim(run_id) || ':' || trim(case_id)        as case_run_id,
    trim(run_id)                                as run_id,
    trim(case_id)                               as case_id,
    trim(status)                                as status,
    trim(model_requested)                       as model_requested,
    cast(started_at as timestamp)               as started_at,

    cast(latency_seconds as double)             as latency_seconds,
    cast(steps as integer)                      as steps,
    cast(tool_calls as integer)                 as tool_calls,
    cast(tool_errors as integer)                as tool_errors,
    cast(input_tokens as bigint)                as input_tokens,
    cast(output_tokens as bigint)               as output_tokens,
    -- Cost is an estimate from tokens x list price, so it needs more than
    -- 2 decimal places: a single case can cost $0.0803.
    cast(cost_usd as decimal(12, 6))            as cost_usd,

    nullif(trim(proposal_id), '')               as proposal_id,
    nullif(trim(classification), '')            as classification,

    _source_file,
    _loaded_at

from source
