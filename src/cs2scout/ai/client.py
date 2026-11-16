"""The one outbound call to Claude (FR-AI-1..4, DRV-12) through the official Anthropic SDK.

Any SDK error becomes ``Upstream`` with a message the Analyst can act on. The API key is
passed in by the caller and never logged or echoed.
"""

from __future__ import annotations

import json
from pathlib import Path

import anthropic

from cs2scout.ai.grounding import SCHEMA

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 32_000  # streamed, so a long answer cannot hit the HTTP timeout
EFFORT = "high"
TIMEOUT_S = 600.0
# Server-side fallback when a safety classifier declines: routes to a model that can answer.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5",
                             "claude-opus-5", "claude-sonnet-5-5"})  # fmt: skip

# List prices in USD per million tokens (input, output), for the cost shown after a brief.
# An estimate: the Anthropic console has the real bill.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-haiku-5-5": (0.10, 0.50), "claude-opus-5": (5.0, 25.0),
          "claude-fable-5-2": (8.0, 40.0)}  # fmt: skip

# The brief's instructions live in a text file, so they are easy to read and tune.
INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text(encoding="utf-8").strip()


class Upstream(RuntimeError):
    pass


def user_message(payload_text: str) -> str:
    return (
        f"Write the anti-strat brief from this evidence.\n\n<evidence>\n{payload_text}\n</evidence>"
    )


def write_brief(
    payload_text: str,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    http_client: anthropic.DefaultHttpxClient | None = None,
) -> tuple[dict, str, dict]:
    """(answer, model that served it, token usage). Raises Upstream on any failure."""
    client = anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_S, http_client=http_client)
    params = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": INSTRUCTIONS,
        "messages": [{"role": "user", "content": user_message(payload_text)}],
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    }
    try:
        if model in FALLBACK_MODELS:
            stream = client.beta.messages.stream(**params, betas=[FALLBACK_BETA],
                                                 fallbacks="default")  # fmt: skip
        else:
            stream = client.messages.stream(**params)
        with stream as events:
            message = events.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise Upstream("Claude rejected the API key (401). Check ANTHROPIC_API_KEY.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise Upstream("This API key may not use that model (403).") from exc
    except anthropic.NotFoundError as exc:
        raise Upstream(f"Model {model!r} was not found (404). Check CS2SCOUT_AI_MODEL.") from exc
    except anthropic.RateLimitError as exc:
        raise Upstream(
            "Claude is rate limiting this key (429). Wait a minute, then try again."
        ) from exc
    except anthropic.BadRequestError as exc:
        raise Upstream(f"Claude rejected the request (400): {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise Upstream(
            f"The Claude API returned an error ({exc.status_code}). Try again later."
        ) from exc
    except anthropic.APITimeoutError as exc:
        raise Upstream("The Claude API did not answer in time. Try again.") from exc
    except anthropic.APIConnectionError as exc:
        raise Upstream("Could not reach the Claude API. Check the internet connection.") from exc
    except anthropic.AnthropicError as exc:
        raise Upstream(f"The Claude API call failed: {type(exc).__name__}") from exc

    if message.stop_reason == "refusal":
        raise Upstream("Claude declined to write this brief.")
    if message.stop_reason == "max_tokens":
        raise Upstream("The brief was cut off before it was finished. Try a narrower filter.")
    # With a fallback, blocks before the last switch point belong to the model that declined.
    blocks = list(message.content)
    switches = [i for i, b in enumerate(blocks) if b.type == "fallback"]
    text = "".join(b.text for b in blocks[switches[-1] + 1 if switches else 0:]
                   if b.type == "text")  # fmt: skip
    try:
        answer = json.loads(text)
    except ValueError as exc:
        raise Upstream("Claude's answer was not valid JSON. Try again.") from exc
    if not isinstance(answer, dict):
        raise Upstream("Claude's answer had an unexpected shape. Try again.")
    usage = {"input_tokens": message.usage.input_tokens,
             "output_tokens": message.usage.output_tokens}  # fmt: skip
    return answer, message.model, usage


def cost_usd(model: str, usage: dict | None) -> float | None:
    """The list-price cost of a call, or None for a model without a known price."""
    price = PRICES.get(model)
    if price is None or not usage:
        return None
    return (usage["input_tokens"] * price[0] + usage["output_tokens"] * price[1]) / 1e6
