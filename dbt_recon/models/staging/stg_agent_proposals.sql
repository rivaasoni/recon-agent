-- ---------------------------------------------------------------------------
-- stg_agent_proposals
--
-- One row per proposal the agent made. Re-running the agent ADDS proposals,
-- so a case can appear several times; picking the latest is a job for the
-- models downstream, not for staging.
-- ---------------------------------------------------------------------------

with source as (

    select * from {{ source('raw', 'agent_proposals') }}

)

select
    trim(proposal_id)                       as proposal_id,
    trim(case_id)                           as case_id,
    cast(created_at as timestamp)           as created_at,
    trim(classification)                    as classification,
    trim(status)                            as status,
    explanation,
    cast(line_count as integer)             as line_count,
    -- The entry total, as money.
    cast(entry_total as decimal(12, 2))     as entry_total,
    lines_json,                             -- the journal lines, left as JSON
    nullif(trim(evidence), '')              as evidence,

    _source_file,
    _loaded_at

from source
