"""The one outbound call to Claude (FR-AI-1..4, DRV-12) through the official Anthropic SDK.

Any SDK error becomes ``Upstream`` with a message the Analyst can act on. The API key is
passed in by the caller and never logged or echoed.
"""

from __future__ import annotations

import json

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

INSTRUCTIONS = """\
You write anti-strat briefs for a Counter-Strike 2 team that is preparing to play an \
opponent. You receive aggregated statistics about that opponent on one map, mined from \
their recent demos by a scouting tool.

Group your claims into sections: t_side (how they play T side), ct_side (how they set up \
and react on CT side), utility (notable grenade use), players (each player's tendencies \
and likely role) and counters (ways to beat these tendencies). Leave out a section that \
has nothing worth saying.

Every claim cites, in finding_ids, the IDs of the findings it is based on, and says \
nothing those findings do not show. Counters are suggestions: cite the findings each one \
answers. Quote how often something happened as the data gives it ("6 of 41 CT rounds"). \
A finding flagged low_sample rests on few rounds: present it as a hint. Refer to players \
by name.

Reading the data: support.k of support.n means seen in k of n eligible rounds, and \
support.demos is how many demos it appears in. outcome.win_pct is the round win rate when \
it happened. recency.share_last_3_demos is the share of occurrences in the three most \
recent demos. Times are seconds into the round.\
"""


class Upstream(RuntimeError):
    pass


def user_message(payload_text: str) -> str:
    return (
        "Write the anti-strat brief from these findings.\n\n"
        f"<findings>\n{payload_text}\n</findings>"
    )


def write_brief(
    payload_text: str,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    http_client: anthropic.DefaultHttpxClient | None = None,
) -> tuple[dict, str]:
    """(answer, model that served it). Raises Upstream on any failure."""
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
    return answer, message.model
