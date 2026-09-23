"""
Token -> dollar cost calculator.

You pay per TOKEN (roughly 3/4 of a word). Prices are per MILLION tokens and
differ for input (what you send) and output (what Claude writes, including
its thinking). Prompt caching adds two more rates: writing to the cache costs
a little more than normal input; reading from it costs a tenth.

Prices are Anthropic first-party API list prices (USD per million tokens).
Check https://www.anthropic.com/pricing if they may have changed.
"""

from __future__ import annotations

# model id -> (input $/M, output $/M)
PRICES_PER_MILLION = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
}

# Relative to the normal input price.
CACHE_WRITE_MULTIPLIER = 1.25   # first time a prefix is cached (5-minute cache)
CACHE_READ_MULTIPLIER = 0.10    # every later reuse of that cached prefix


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Dollar cost of one API response's usage.

    `input_tokens` from the API EXCLUDES cached tokens, which are reported
    separately — so the three input counts are simply added together here.
    """
    if model not in PRICES_PER_MILLION:
        raise ValueError(
            f"No price for model '{model}'. Add it to PRICES_PER_MILLION in recon/agent/costs.py."
        )
    input_price, output_price = PRICES_PER_MILLION[model]
    per_token_in = input_price / 1_000_000
    per_token_out = output_price / 1_000_000

    return (
        input_tokens * per_token_in
        + cache_write_tokens * per_token_in * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * per_token_in * CACHE_READ_MULTIPLIER
        + output_tokens * per_token_out
    )
