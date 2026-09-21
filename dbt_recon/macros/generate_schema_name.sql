{#
    Controls which schema each model is built in.

    dbt's default glues the target schema onto your custom one, so a model
    configured with `+schema: staging` lands in `main_staging`. That default
    exists so several developers sharing one warehouse don't overwrite each
    other. We have one local DuckDB file, so we override it to use the name
    as written:  +schema: staging  ->  staging

    This exact override is the pattern documented by dbt.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
