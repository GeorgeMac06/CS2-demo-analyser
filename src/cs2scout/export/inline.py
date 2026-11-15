"""Building blocks for the self-contained export (FR-EXP-1..2, DRV-6, C-2; design §6.4)."""

from __future__ import annotations

import base64
import re
from pathlib import Path

# Nothing may load from the network: scripts and styles are inline, images are data: URIs.
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src data:; font-src data:")  # fmt: skip

_STEAMID = re.compile(r"7656119\d{10}")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:[\\/](?:Users|Documents|Program)", re.IGNORECASE)
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def data_uri(path: Path, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def leaks(html: str) -> list[str]:
    """Personal data an export must never contain (I-3, C-2). Empty list = safe to share."""
    found = []
    if _STEAMID.search(html):
        found.append("a SteamID")
    if _WINDOWS_PATH.search(html):
        found.append("a file path from this PC")
    return found


def filename(*parts: str) -> str:
    cleaned = "-".join(_UNSAFE_NAME.sub("_", p).strip("_") for p in parts if p)
    return f"{cleaned or 'scouting'}.html"
