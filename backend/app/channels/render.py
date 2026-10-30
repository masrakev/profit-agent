"""Render verified text for a channel, escaping everything that is not ours.

Input text (model or template output) cites facts as `{{F<id>}}` and entities as
`{{E:<kind>[:<uuid>]}}`. Rendering is one pass over the text: each reference is replaced by the
fact's formatted value or the entity's name, and every other piece of text is escaped. Names are
merchant-provided (products, campaigns, ad text) and treated as hostile:

- every channel: control, zero-width and bidirectional-override characters are removed, line
  breaks and tabs become spaces, and long names are cut;
- HTML (web, email): HTML-escaped, quotes included;
- WhatsApp (plain text): its formatting markers (`*` `_` `~` and backtick) are replaced by
  look-alike characters so a name cannot restyle the message, and links are defanged so a name
  cannot become a clickable URL;
- plain text (an email's text part, a subject line): links are defanged, nothing else changes.

A substituted name is never scanned again, so a product named `{{F1}}` stays that text.
"""

import html
import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Connection, text

from app.domain.text import LINE_BREAKS, strip_invisible
from app.facts.model import Fact
from app.verifier.render import (
    ENTITY_REFERENCE,
    REFERENCE,
    UnknownFactReferenceError,
    format_fact,
)

MAX_NAME_CHARS = 120
_ANY_REFERENCE = re.compile(f"{REFERENCE.pattern}|{ENTITY_REFERENCE.pattern}")
_WHATSAPP_MARKERS = str.maketrans({"*": "∗", "_": "＿", "~": "∼", "`": "ˋ"})
_SCHEME = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*)://")
_WWW = re.compile(r"(?i)\bwww\.")


class Channel(StrEnum):
    WEB = "web"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    TEXT = "text"

    @property
    def is_html(self) -> bool:
        return self in (Channel.WEB, Channel.EMAIL)


class UnknownEntityReferenceError(KeyError):
    pass


def clean(value: str, *, single_line: bool) -> str:
    out = strip_invisible(value)
    if single_line:
        out = re.sub(r" {2,}", " ", LINE_BREAKS.sub(" ", out)).strip()
    return out


def _defang(value: str) -> str:
    return _WWW.sub("www[.]", _SCHEME.sub(r"\1[:]//", value))


def _whatsapp(value: str) -> str:
    return _defang(value).translate(_WHATSAPP_MARKERS)


def escape(value: str, channel: Channel, *, single_line: bool = False) -> str:
    cleaned = clean(value, single_line=single_line)
    if channel.is_html:
        return html.escape(cleaned, quote=True)
    return _defang(cleaned) if channel is Channel.TEXT else _whatsapp(cleaned)


def escape_name(name: str, channel: Channel) -> str:
    """A merchant-provided name, safe to show on `channel`."""
    cleaned = clean(name, single_line=True)
    if len(cleaned) > MAX_NAME_CHARS:
        cleaned = cleaned[: MAX_NAME_CHARS - 1] + "…"
    return escape(cleaned, channel, single_line=True)


def render(
    text_: str, facts: Mapping[int, Fact], names: Mapping[str, str], channel: Channel
) -> str:
    """`names` maps `store`, `product:<uuid>` and `campaign:<uuid>` to raw merchant names."""
    out: list[str] = []
    position = 0
    for match in _ANY_REFERENCE.finditer(text_):
        out.append(escape(text_[position : match.start()], channel))
        fact_id, entity = match.group(1), match.group(2)
        if fact_id is not None:
            fact = facts.get(int(fact_id))
            if fact is None:
                raise UnknownFactReferenceError(int(fact_id))
            out.append(escape(format_fact(fact), channel))
        else:
            if entity not in names:
                raise UnknownEntityReferenceError(entity)
            out.append(escape_name(names[entity], channel))
        position = match.end()
    out.append(escape(text_[position:], channel))
    return "".join(out)


def load_entity_names(conn: Connection, store_id: UUID, refs: Iterable[str]) -> dict[str, str]:
    """Raw names of the referenced entities, read under the store's row-level security."""
    names: dict[str, str] = {}
    by_kind: dict[str, list[UUID]] = {"product": [], "campaign": []}
    for ref in set(refs):
        if ref == "store":
            row = conn.execute(
                text("SELECT name FROM stores WHERE store_id = :s"), {"s": store_id}
            ).scalar()
            if row is not None:
                names["store"] = str(row)
        else:
            kind, _, ident = ref.partition(":")
            by_kind[kind].append(UUID(ident))
    for kind, table in (("product", "products"), ("campaign", "ad_campaigns")):
        if by_kind[kind]:
            rows = conn.execute(
                text(f"SELECT id, name FROM {table} WHERE store_id = :s AND id = ANY(:ids)"),
                {"s": store_id, "ids": by_kind[kind]},
            )
            names.update({f"{kind}:{r.id}": str(r.name) for r in rows})
    return names
