"""Recognition biasing: the store's campaign and product names, the words an owner says that a
speech model is least likely to know (the endpoint's `keywords`).

The names are merchant text, so they are passed as data and cleaned like any store text:
invisible characters dropped, whitespace collapsed, at most `MAX_KEYWORD_CHARS` long (a longer
name is left out rather than cut into a word nobody says), never one that reads like an
instruction or holds data-block delimiters, at most `MAX_KEYWORDS` of them.
"""

import re
from uuid import UUID

from sqlalchemy import Connection, select

from app.agent.llm.transcribe import MAX_KEYWORD_CHARS, MAX_KEYWORDS
from app.agent.untrusted import contains_block_delimiters, looks_like_instruction
from app.domain.schema import ad_campaigns, products
from app.domain.text import strip_invisible

_SPACE = re.compile(r"\s+")
_LETTER = re.compile(r"[^\W\d_]")


def keyword(name: str) -> str | None:
    """The name as a keyword, or None when it must not be one."""
    cleaned = _SPACE.sub(" ", strip_invisible(name)).strip()
    if not cleaned or len(cleaned) > MAX_KEYWORD_CHARS or not _LETTER.search(cleaned):
        return None
    if looks_like_instruction(cleaned) or contains_block_delimiters(cleaned):
        return None
    return cleaned


def store_keywords(conn: Connection, store_id: UUID) -> tuple[str, ...]:
    """Campaign names first (few, and rarely ordinary words), then product names."""
    names = [
        *conn.execute(
            select(ad_campaigns.c.name)
            .where(ad_campaigns.c.store_id == store_id)
            .order_by(ad_campaigns.c.name)
        ).scalars(),
        *conn.execute(
            select(products.c.name).where(products.c.store_id == store_id).order_by(products.c.name)
        ).scalars(),
    ]
    found: dict[str, str] = {}
    for name in names:
        kept = keyword(name)
        if kept is not None:
            found.setdefault(kept.casefold(), kept)
    return tuple(found.values())[:MAX_KEYWORDS]
