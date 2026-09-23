"""Tests for the token -> dollar cost calculator. No API calls."""

import pytest

from recon.agent.costs import cost_usd


def test_one_million_input_tokens_costs_the_list_price():
    assert cost_usd("claude-opus-5", 1_000_000, 0) == pytest.approx(5.00)


def test_output_tokens_cost_more_than_input():
    assert cost_usd("claude-opus-5", 0, 1_000_000) == pytest.approx(25.00)


def test_a_typical_small_call():
    # 20 input + 50 output tokens on Opus 5:
    # 20 * $5/M + 50 * $25/M = $0.0001 + $0.00125
    assert cost_usd("claude-opus-5", 20, 50) == pytest.approx(0.00135)


def test_cache_reads_cost_a_tenth_of_normal_input():
    normal = cost_usd("claude-opus-5", 10_000, 0)
    cached = cost_usd("claude-opus-5", 0, 0, cache_read_tokens=10_000)
    assert cached == pytest.approx(normal * 0.10)


def test_unknown_model_is_a_clear_error():
    with pytest.raises(ValueError, match="No price for model"):
        cost_usd("claude-imaginary-9", 100, 100)
