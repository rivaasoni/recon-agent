-- ---------------------------------------------------------------------------
-- stg_agent_decisions
--
-- One row per human approve/reject decision. The log is append-only, so a
-- proposal can have several decisions; the latest one is the current answer.
-- ---------------------------------------------------------------------------

with source as (

    select * from {{ source('raw', 'agent_decisions') }}

)

select
    trim(decision_id)                   as decision_id,
    trim(proposal_id)                   as proposal_id,
    trim(case_id)                       as case_id,
    cast(decided_at as timestamp)       as decided_at,
    lower(trim(decision))               as decision,      -- 'approved' / 'rejected'
    trim(reviewer)                      as reviewer,
    nullif(trim(note), '')              as note,

    _source_file,
    _loaded_at

from source
