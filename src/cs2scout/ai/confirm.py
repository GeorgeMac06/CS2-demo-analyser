"""The confirmation token (FR-AI-2, design §6.5).

The preview returns a token that is an HMAC of the entry and the payload hash, valid for
10 minutes. Sending requires it, so a call can only carry a payload the Analyst has seen:
if the filters or the analysis change after the preview, the hash no longer matches.
"""

from __future__ import annotations

import hashlib
import hmac

TTL_S = 600


def make(secret: bytes, entry_id: int, payload_hash: str, now: float) -> str:
    expires = int(now) + TTL_S
    return f"{expires}.{_mac(secret, entry_id, payload_hash, expires)}"


def valid(secret: bytes, token: str, entry_id: int, payload_hash: str, now: float) -> bool:
    expires_text, _, mac = token.partition(".")
    if not expires_text.isdigit() or not mac:
        return False
    expires = int(expires_text)
    expected = _mac(secret, entry_id, payload_hash, expires)
    return hmac.compare_digest(mac, expected) and now <= expires


def _mac(secret: bytes, entry_id: int, payload_hash: str, expires: int) -> str:
    message = f"{entry_id}:{payload_hash}:{expires}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()
