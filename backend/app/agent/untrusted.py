"""Untrusted text as delimited, escaped data blocks (invariant 8, ADR 0010).

Product names, campaign (ad) names and any other store-provided text reach the model only inside
a block like

    ⟦data kind=product_name⟧Blue mug⟦/data⟧

never in the system prompt. The content is escaped so it cannot close the block or open a new
one: the delimiter characters are replaced, control characters (except tab and newline) are
dropped, and the text is truncated. The system prompt states that block content is data to
describe, never instructions to follow.
"""

import re

from app.domain.text import strip_invisible

OPEN, CLOSE = "⟦", "⟧"
MAX_CHARS = 200
_KIND = re.compile(r"^[a-z_]{1,32}$")


def escape(text: str, max_chars: int = MAX_CHARS) -> str:
    cleaned = strip_invisible(text).replace(OPEN, "[").replace(CLOSE, "]")
    return cleaned if len(cleaned) <= max_chars else cleaned[: max_chars - 1] + "…"


def data_block(kind: str, text: str) -> str:
    if not _KIND.match(kind):
        raise ValueError(f"invalid data block kind {kind!r}")
    return f"{OPEN}data kind={kind}{CLOSE}{escape(text)}{OPEN}/data{CLOSE}"


def contains_block_delimiters(text: str) -> bool:
    return OPEN in text or CLOSE in text
