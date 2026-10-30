"""Briefings, alerts and decisions rendered for email: an HTML part and a plain-text part.

Everything is written by code from a document (app.briefings.models.Document): fact references
become formatted facts, entity references escaped names, and every other string is escaped too
(`app.channels.render`). Links come from ids only: evidence (an incident), review (a decision)
and approve, a signed single-use approval link opened on the web platform's confirmation page
(the token in the URL fragment, so it reaches no server log; opening it decides nothing).
"""

import html
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import Connection

from app.briefings.models import BriefingContent, BriefingKind, Button, ButtonKind, Document
from app.channels.render import Channel, clean, escape, load_entity_names, render
from app.facts.model import Fact
from app.facts.repository import get_facts

MAX_SUBJECT_CHARS = 180
LEVEL_COLORS = {
    "critical": "#b91c1c",
    "high": "#c2410c",
    "normal": "#a16207",
    "data_quality": "#1d4ed8",
    "watchlist": "#57534e",
}
LEVEL_WORDS = {
    "critical": "critical",
    "high": "high",
    "normal": "normal",
    "data_quality": "data issue",
    "watchlist": "watchlist",
}
FOOTER = (
    "Every number in this message is a fact with its formula and source rows: open it in "
    "Profit Agent to check it. You receive this message because email is one of this store's "
    "channels."
)


@dataclass(frozen=True)
class Links:
    app_base_url: str
    # (decision id, option id) -> a signed approval token, or None when links are not set up
    approval_token: Callable[[str, str], str | None] | None = None

    def url(self, button: Button) -> str | None:
        base = self.app_base_url.rstrip("/")
        if button.kind is ButtonKind.EVIDENCE and button.incident_id:
            return f"{base}/incidents/{quote(button.incident_id, safe='')}"
        if button.kind is ButtonKind.REVIEW and button.decision_id:
            return f"{base}/decisions/{UUID(button.decision_id)}"
        if (
            button.kind is ButtonKind.APPROVE
            and button.decision_id
            and button.option_id
            and self.approval_token is not None
        ):
            token = self.approval_token(button.decision_id, button.option_id)
            return f"{base}/approve#token={quote(token, safe='')}" if token else None
        return None

    @property
    def settings_url(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/settings"


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class Inputs:
    facts: Mapping[int, Fact]
    names: Mapping[str, str]

    @property
    def store(self) -> str:
        return self.names.get("store", "your store")


def load_inputs(conn: Connection, store_id: UUID, document: Document) -> Inputs:
    """The facts and raw names a document cites (under the store's row-level security)."""
    return Inputs(
        facts=get_facts(conn, store_id, document.fact_ids),
        names=load_entity_names(conn, store_id, {"store", *document.entities}),
    )


def briefing_title(content: BriefingContent) -> str:
    start, end = content.period_start, content.period_end
    if content.kind is BriefingKind.DAILY:
        return f"Daily brief, {start:%A %d %B %Y}"
    if content.kind is BriefingKind.WEEKLY:
        return f"Weekly report, {start:%d %B} to {end - timedelta(days=1):%d %B %Y}"
    return f"Monthly review, {start:%B %Y}"


def _subject(store: str, title: str | None, headline: str) -> str:
    parts = [clean(store, single_line=True)]
    if title:
        parts.append(title)
    parts.append(clean(headline, single_line=True))
    subject = ": ".join(parts)
    if len(subject) > MAX_SUBJECT_CHARS:
        subject = subject[: MAX_SUBJECT_CHARS - 1] + "…"
    return subject


# --- HTML ------------------------------------------------------------------------------------

STYLE_BODY = (
    "margin:0;padding:0;background:#f5f5f4;color:#1c1917;"
    "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;"
    "line-height:1.5"
)
STYLE_CARD = "max-width:600px;width:100%;background:#ffffff;border-radius:8px"
STYLE_BUTTON = (
    "display:inline-block;margin:4px 8px 0 0;padding:6px 12px;border-radius:6px;"
    "background:#1c1917;color:#ffffff;text-decoration:none;font-size:13px"
)
STYLE_LINK = (
    "display:inline-block;margin:4px 8px 0 0;padding:6px 12px;border-radius:6px;"
    "border:1px solid #d6d3d1;color:#1c1917;text-decoration:none;font-size:13px"
)


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


def _buttons_html(buttons: Iterable[Button], links: Links) -> str:
    out = []
    for button in buttons:
        url = links.url(button)
        if url is None:
            continue
        style = STYLE_BUTTON if button.kind is ButtonKind.APPROVE else STYLE_LINK
        out.append(
            f'<a href="{_attr(url)}" style="{style}">{escape(button.label, Channel.EMAIL)}</a>'
        )
    return f'<div style="margin-top:4px">{"".join(out)}</div>' if out else ""


def _level_html(level: str | None) -> str:
    if level is None or level not in LEVEL_WORDS:
        return ""
    return (
        f'<span style="display:inline-block;margin-right:6px;padding:1px 6px;border-radius:4px;'
        f'background:{LEVEL_COLORS[level]};color:#ffffff;font-size:12px">'
        f"{escape(LEVEL_WORDS[level], Channel.EMAIL)}</span>"
    )


def _html(
    document: Document,
    title: str | None,
    narrative: str | None,
    inputs: Inputs,
    links: Links,
    subject: str,
) -> str:
    def text(value: str) -> str:
        return render(value, inputs.facts, inputs.names, Channel.EMAIL)

    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(subject, Channel.EMAIL, single_line=True)}</title></head>",
        f'<body style="{STYLE_BODY}">',
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        '<td align="center" style="padding:24px 12px">',
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="{STYLE_CARD}"><tr>'
        '<td style="padding:24px">',
        f'<p style="margin:0 0 4px;font-size:13px;color:#57534e">'
        f"{escape(inputs.store, Channel.EMAIL, single_line=True)}"
        + (f" &middot; {escape(title, Channel.EMAIL)}" if title else "")
        + "</p>",
        f'<h1 style="margin:0 0 16px;font-size:20px">{text(document.headline)}</h1>',
    ]
    if narrative:
        parts.append(f'<p style="margin:0 0 16px">{text(narrative)}</p>')
    for section in document.sections:
        parts.append(
            f'<h2 style="margin:20px 0 8px;font-size:16px">'
            f"{escape(section.title, Channel.EMAIL)}</h2>"
        )
        for item in section.items:
            parts.append(
                f'<div style="margin:0 0 10px">{_level_html(item.level)}{text(item.text)}'
                f"{_buttons_html(item.buttons, links)}</div>"
            )
        if section.table is not None:
            head = "".join(
                f'<th align="left" style="padding:4px 8px;border-bottom:1px solid #d6d3d1;'
                f'font-size:12px">{escape(c, Channel.EMAIL)}</th>'
                for c in section.table.columns
            )
            rows = "".join(
                "<tr>"
                + "".join(
                    f'<td style="padding:4px 8px;border-bottom:1px solid #f5f5f4;font-size:13px">'
                    f"{text(cell)}</td>"
                    for cell in row
                )
                + "</tr>"
                for row in section.table.rows
            )
            parts.append(
                '<table role="presentation" cellpadding="0" cellspacing="0" width="100%">'
                f"<tr>{head}</tr>{rows}</table>"
            )
        if not section.items and section.table is None and section.empty:
            empty = escape(section.empty, Channel.EMAIL)
            parts.append(f'<p style="margin:0 0 10px;color:#78716c">{empty}</p>')
    parts.append(
        f'<p style="margin:24px 0 0;font-size:12px;color:#78716c">{escape(FOOTER, Channel.EMAIL)} '
        f'<a href="{_attr(links.settings_url)}" style="color:#57534e">Settings</a></p>'
    )
    parts.append("</td></tr></table></td></tr></table></body></html>")
    return "\n".join(parts) + "\n"


# --- plain text ------------------------------------------------------------------------------


def _text(
    document: Document, title: str | None, narrative: str | None, inputs: Inputs, links: Links
) -> str:
    def text(value: str) -> str:
        return render(value, inputs.facts, inputs.names, Channel.TEXT)

    lines = [escape(inputs.store, Channel.TEXT, single_line=True)]
    if title:
        lines.append(title)
    lines += [text(document.headline), ""]
    if narrative:
        lines += [text(narrative), ""]
    for section in document.sections:
        lines.append(f"== {section.title} ==")
        for item in section.items:
            level = f"[{LEVEL_WORDS[item.level]}] " if item.level in LEVEL_WORDS else ""
            lines.append(f"- {level}{text(item.text)}")
            for button in item.buttons:
                url = links.url(button)
                if url is not None:
                    lines.append(f"  {button.label}: {url}")
        if section.table is not None:
            for row in section.table.rows:
                cells = [text(c) for c in row]
                pairs = "; ".join(
                    f"{col}: {cell}"
                    for col, cell in zip(section.table.columns[1:], cells[1:], strict=True)
                )
                lines.append(f"- {cells[0]}: {pairs}")
        if not section.items and section.table is None and section.empty:
            lines.append(section.empty)
        lines.append("")
    lines += [FOOTER, f"Settings: {links.settings_url}"]
    return "\n".join(lines) + "\n"


def render_document(
    document: Document,
    inputs: Inputs,
    links: Links,
    *,
    title: str | None = None,
    narrative: str | None = None,
) -> Rendered:
    subject = _subject(
        inputs.store, title, render(document.headline, inputs.facts, inputs.names, Channel.TEXT)
    )
    return Rendered(
        subject=subject,
        text=_text(document, title, narrative, inputs, links),
        html=_html(document, title, narrative, inputs, links, subject),
    )


def render_briefing(
    content: BriefingContent, narrative: str | None, inputs: Inputs, links: Links
) -> Rendered:
    return render_document(
        content, inputs, links, title=briefing_title(content), narrative=narrative
    )
