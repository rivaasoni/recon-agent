-- ---------------------------------------------------------------------------
-- stg_documents
--
-- One row per supporting document.
-- We add two convenience columns parsed straight from the source — a short
-- ID and the document type from the first line. That is light parsing of the
-- data we already have, not business logic, so it belongs in staging.
-- ---------------------------------------------------------------------------

with source as (

    select * from {{ source('raw', 'documents') }}

),

cleaned as (

    select
        -- 'DOC-007.txt' -> 'DOC-007'
        replace(file_name, '.txt', '')                              as doc_id,

        -- Every document starts with a line like "DOCUMENT: Vendor bill".
        -- regexp_extract pulls out the part in brackets ( ... ):
        --   ^           start of the text
        --   DOCUMENT:   the literal label
        --   ([^\n]*)    everything up to the end of that first line
        regexp_extract(content, '^DOCUMENT: ([^\n]*)', 1)           as doc_type,

        trim(content)                                               as content,

        _source_file,
        _loaded_at

    from source

)

select * from cleaned
