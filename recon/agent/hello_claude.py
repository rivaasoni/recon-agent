"""
Phase 6, Step 1: one tiny Claude API call, to prove the setup works.

Checks that your API key is valid and the model name is right, and shows
what one call costs. Expected cost: well under $0.01.

Run it:
    python -m recon.agent.hello_claude
"""

from __future__ import annotations

import anthropic

from recon.agent.costs import cost_usd
from recon.config import settings


def main() -> None:
    # settings.anthropic_api_key() raises a helpful error if .env still has
    # the placeholder key.
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key())

    try:
        response = client.beta.messages.create(
            model=settings.model,
            max_tokens=2000,
            # Claude decides for itself how much to think. (Recommended for
            # Opus 5; the old fixed "budget_tokens" setting is rejected.)
            thinking={"type": "adaptive"},
            # Server-side fallbacks: if the request is ever declined by a
            # safety classifier, the API retries it on a fallback model
            # instead of failing. response.model says who actually answered.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{
                "role": "user",
                "content": "In one sentence, what is a bank reconciliation?",
            }],
        )
    except anthropic.AuthenticationError:
        raise SystemExit("The API rejected your key. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.NotFoundError:
        raise SystemExit(f"Model '{settings.model}' not found. Check RECON_MODEL in .env.")

    # Always check WHY Claude stopped before reading the answer.
    if response.stop_reason == "refusal":
        raise SystemExit("The request was declined (stop_reason='refusal').")

    # response.content is a LIST of blocks (thinking, text, ...). Print the text.
    answer = "".join(block.text for block in response.content if block.type == "text")
    usage = response.usage

    print(f"Answer: {answer}\n")
    print(f"Model that answered: {response.model}")
    print(f"Stop reason:         {response.stop_reason}")
    print(f"Input tokens:        {usage.input_tokens}")
    print(f"Output tokens:       {usage.output_tokens}   (includes any thinking)")
    print(f"Cost:                ${cost_usd(response.model, usage.input_tokens, usage.output_tokens):.5f}")


if __name__ == "__main__":
    main()
