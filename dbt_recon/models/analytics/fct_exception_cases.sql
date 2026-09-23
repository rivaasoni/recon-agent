-- ---------------------------------------------------------------------------
-- fct_exception_cases   (the fact table for BI)
--
-- GRAIN: one row per exception case — its current state.
--
-- Brings together:
--   the case facts            (matching.exceptions)
--   the agent's LATEST proposal   (stg_agent_proposals)
--   the CURRENT human decision    (stg_agent_decisions on that proposal)
--   the LATEST run's stats        (stg_agent_case_runs)
--
-- Definitions worth knowing before using any number built on this table:
--   break_value   - the money at stake in the case (see below)
--   review_status - no_proposal -> pending -> approved / rejected
--   "current" decision = the latest decision ON THE LATEST PROPOSAL. A
--   decision about a superseded proposal is history, not current state.
-- ---------------------------------------------------------------------------

with cases as (

    select * from {{ ref('exceptions') }}

),

-- The agent's latest word on each case. QUALIFY filters on a window
-- function directly: "keep only the newest row per case_id".
latest_proposal as (

    select *
    from {{ ref('stg_agent_proposals') }}
    qualify row_number() over (
        partition by case_id order by created_at desc, proposal_id desc
    ) = 1

),

-- The newest decision per proposal (a reviewer may change their mind).
latest_decision as (

    select *
    from {{ ref('stg_agent_decisions') }}
    qualify row_number() over (
        partition by proposal_id order by decided_at desc, decision_id desc
    ) = 1

),

-- How the most recent run went for each case.
latest_run as (

    select *
    from {{ ref('stg_agent_case_runs') }}
    qualify row_number() over (
        partition by case_id order by started_at desc, run_id desc
    ) = 1

)

select
    cases.case_id,
    cases.case_shape,
    cases.reference,
    cases.case_date,
    cases.bank_txn_id,
    cases.gl_entry_id,
    cases.bank_amount,
    cases.ledger_amount,
    cases.amount_difference,
    cases.ledger_currency,
    cases.reference_matched_elsewhere,

    -- The money at stake. Two-sided cases differ by an amount; one-sided
    -- cases are entirely unmatched, so the whole row is the break.
    abs(case
        when cases.case_shape = 'both_sides'  then cases.amount_difference
        when cases.case_shape = 'bank_only'   then cases.bank_amount
        else cases.ledger_amount
    end)                                                as break_value,

    -- --- The agent ---------------------------------------------------------
    latest_proposal.proposal_id,
    latest_proposal.classification,
    latest_proposal.created_at                          as proposed_at,
    latest_proposal.entry_total,
    latest_proposal.line_count,
    -- Some fixes are "do nothing" (e.g. a timing difference clears itself).
    coalesce(latest_proposal.line_count, 0) > 0         as proposes_entry,

    -- --- The human ---------------------------------------------------------
    latest_decision.decision,
    latest_decision.reviewer,
    latest_decision.decided_at,
    latest_decision.note                                as reviewer_note,

    case
        when latest_proposal.proposal_id is null then 'no_proposal'
        when latest_decision.decision is null    then 'pending'
        else latest_decision.decision
    end                                                 as review_status,

    -- Still needs a human: nothing proposed, or proposed but not decided.
    latest_decision.decision is null                    as is_open,

    -- --- The run that produced the proposal --------------------------------
    latest_run.run_id,
    latest_run.status                                   as run_status,
    latest_run.model_requested,
    latest_run.steps,
    latest_run.tool_calls,
    latest_run.tool_errors,
    latest_run.cost_usd,
    latest_run.latency_seconds

from cases
left join latest_proposal on cases.case_id = latest_proposal.case_id
-- Joined via the PROPOSAL, so a decision on an older proposal is ignored.
left join latest_decision on latest_proposal.proposal_id = latest_decision.proposal_id
left join latest_run      on cases.case_id = latest_run.case_id
