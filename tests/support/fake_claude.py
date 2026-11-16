"""A fake Anthropic API at the HTTP layer (T-14): the real SDK runs, only the network is faked."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import anthropic
import httpx2

Reply = Callable[[dict], httpx2.Response]


class FakeClaude:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.reply: Reply = lambda body: stream(cite_everything(body))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.requests.append({"url": str(request.url), "headers": dict(request.headers),
                              "body": body, "raw": request.content.decode()})  # fmt: skip
        return self.reply(body)

    def http_client(self) -> anthropic.DefaultHttpxClient:
        return anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(self._handle))


def sent_payload(body: dict) -> dict:
    """The findings payload inside the request's user message."""
    text = body["messages"][0]["content"]
    return json.loads(re.search(r"<evidence>\n(.*)\n</evidence>", text, re.S).group(1))


def round_ids(body: dict) -> list[str]:
    """The round IDs the payload's stories start with."""
    return [story.split(" ", 1)[0] for story in sent_payload(body)["rounds"]]


def cite_everything(body: dict) -> dict:
    """A well-behaved answer: one claim per finding (up to 12), each citing its finding, and
    a pistol round and a round to watch citing round stories."""
    findings = sent_payload(body)["findings"][:12]
    rounds = round_ids(body)
    return {"sections": [
        {"id": "t_side", "claims": [{"text": f"They often do this: {f['title']}.",
                                     "finding_ids": [f["id"]], "rounds": []}
                                    for f in findings[:8]]},
        {"id": "pistols", "claims": [{"text": "On the T pistol they rush B together.",
                                      "finding_ids": [], "rounds": rounds[:1]}]},
        {"id": "watch", "claims": [{"text": "Watch how the lurker moves at 1:25.",
                                    "finding_ids": [], "rounds": rounds[1:3]}]},
        {"id": "counters", "claims": [{"text": "Stack the site they hit most.",
                                       "finding_ids": [f["id"]], "rounds": []}
                                      for f in findings[8:]]},
    ]}  # fmt: skip


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def stream(answer: dict | str, *, stop_reason: str = "end_turn",
           model: str = "claude-opus-5-5") -> httpx2.Response:  # fmt: skip
    """A streamed Messages API response whose one text block is ``answer``."""
    text = answer if isinstance(answer, str) else json.dumps(answer)
    message = {"id": "msg_fake", "type": "message", "role": "assistant", "model": model,
               "content": [], "stop_reason": None, "stop_sequence": None,
               "usage": {"input_tokens": 100, "output_tokens": 1}}  # fmt: skip
    half = len(text) // 2
    sse = "".join([
        _event("message_start", {"type": "message_start", "message": message}),
        _event("content_block_start", {"type": "content_block_start", "index": 0,
                                       "content_block": {"type": "text", "text": ""}}),
        *(_event("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": part}})
          for part in (text[:half], text[half:])),
        _event("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _event("message_delta", {"type": "message_delta",
                                 "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                                 "usage": {"output_tokens": 50}}),
        _event("message_stop", {"type": "message_stop"}),
    ])  # fmt: skip
    return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                           content=sse.encode())  # fmt: skip


def error(status: int, kind: str, message: str) -> httpx2.Response:
    # x-should-retry: false keeps the SDK from retrying, so each test sees one request.
    body = {"type": "error", "error": {"type": kind, "message": message}}
    headers = {"x-should-retry": "false", "request-id": "req_fake"}
    return httpx2.Response(status, headers=headers, json=body)
