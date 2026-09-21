-- ---------------------------------------------------------------------------
-- documents  (cleaned layer)
--
-- Supporting documents the agent can search in Phase 5.
-- Adds a short doc_type code and the invoice/bill reference each document is
-- about, so a tool can look documents up by reference with a simple WHERE.
-- ---------------------------------------------------------------------------

with staged as (

    select * from {{ ref('stg_documents') }}

)

select
    doc_id,

    -- Long human titles -> short, stable codes that are easy to filter on.
    case
        when doc_type = 'Vendor bill'                  then 'vendor_bill'
        when doc_type = 'Customer invoice'             then 'customer_invoice'
        when doc_type = 'Customer remittance advice'   then 'remittance_advice'
        when doc_type = 'Accounts payable payment run' then 'ap_payment_run'
        when doc_type like '%Wire Confirmation'        then 'wire_confirmation'
        when doc_type like '%Fee Schedule'             then 'fee_schedule'
        else 'unknown'
    end as doc_type,

    doc_type as doc_title,

    -- The first INV-#### or BILL-#### in the text. NULL for the fee
    -- schedule, which isn't about any one transaction.
    nullif(regexp_extract(content, '(INV|BILL)-[0-9]+'), '') as primary_reference,

    content,

    _source_file,
    _loaded_at

from staged
