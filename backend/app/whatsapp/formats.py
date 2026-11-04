"""Short WhatsApp messages (ADR 0027): an alert, the daily brief, a decision's status, a goal's
progress, Ask's answers, and the few fixed replies.

They are cut from the same documents as email (app.briefings), written by code: every number is
a fact rendered by app.channels.render (estimates as their P10-P90 range), every merchant name is
escaped for WhatsApp (its formatting markers neutralised, links defanged), and only code adds
formatting around rendered text. Each message has the approved template that says the same in
one-line parameters, for when the owner has not written in the last 24 hours.

- alert: what was detected, the impact (a range), the recommended option; buttons "Approve" (a
  signed single-use token, app.whatsapp.buttons) and "See options";
- daily brief: the health line and the top item;
- decision status: proposed, approved, done, failed, rejected, expired or replaced;
- goal progress: the weekly tracking line of the weekly report.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection

from app.agent.ask import AskResult
from app.agent.contracts import Flag
from app.briefings import wording
from app.briefings.content import entity_ref, goal_item
from app.briefings.models import BriefingContent, BriefingKind, ButtonKind, Document, Item
from app.briefings.notices import alert_document, decision_document, notice_context
from app.channels.messages import briefing_title, load_inputs
from app.channels.render import Channel, escape, load_entity_names, render
from app.channels.whatsapp import ReplyButton, WhatsAppMessage
from app.decisions.store import DecisionStatus, DecisionView, get
from app.detection.models import AlertLevel, Incident
from app.facts.repository import get_facts
from app.goals import service as goal_service
from app.verifier import entity_references, fact_references
from app.whatsapp.buttons import approve_button, goal_button, options_button

FOOTER = "Every number is a fact you can check in Merit."
HELP = (
    "Ask me about your store: profit, campaigns, products, stock, or a goal you want to reach "
    "by a date. You can also send a voice note. A decision is approved with its button here or "
    "in Merit; nothing written here approves anything."
)
REFUSAL = (
    "Hello. This number only talks to the owners of the stores it serves, from a number they "
    "verified in their store's settings. Nothing you send here is read."
)
TEMPLATES = {
    "alert": "profit_alert",  # {{1}} headline, {{2}} impact, {{3}} recommendation; 2 buttons
    "data": "data_alert",  # {{1}} headline, {{2}} why, {{3}} next step
    "brief": "daily_brief",  # {{1}} title, {{2}} health, {{3}} top item
    "decision": "decision_update",  # {{1}} status
    "goal": "goal_update",  # {{1}} progress
}
STATUS_WORDS = {
    DecisionStatus.APPROVED: "Approved for {entity}: {option}. It runs within your spending caps.",
    DecisionStatus.EXECUTING: "Approved for {entity}: {option}. It is being executed.",
    DecisionStatus.EXECUTED: "Done for {entity}: {option}. It can be undone in Merit.",
    DecisionStatus.MEASURED: "Measured for {entity}: what this change earned is in Merit "
    "({option}).",
    DecisionStatus.FAILED: "Not done for {entity}: {option} could not be executed; nothing "
    "changed.",
    DecisionStatus.REJECTED: "Rejected for {entity}: {option}. Nothing changes.",
    DecisionStatus.EXPIRED: "Expired for {entity}: nobody approved it ({option}); nothing changed.",
    DecisionStatus.SUPERSEDED: "Replaced: a decision on more recent data acts on {entity} instead.",
}


@dataclass(frozen=True)
class Formats:
    app_base_url: str
    secret: str | None  # signs decision and goal buttons; without it, no button decides
    now: datetime

    def _link(self, path: str) -> str:
        return f"{self.app_base_url.rstrip('/')}/{path}"

    def _approve(
        self, conn: Connection, store_id: UUID, decision_id: str, option_id: str
    ) -> ReplyButton | None:
        if self.secret is None:  # without it no button decides
            return None
        if get(conn, store_id, UUID(decision_id)).status is not DecisionStatus.PROPOSED:
            return None  # decided, expired or replaced: nothing left to approve
        token = approve_button(
            conn, store_id, UUID(decision_id), option_id, secret=self.secret, now=self.now
        )
        return ReplyButton(token, "Approve")

    def _buttons(self, conn: Connection, store_id: UUID, item: Item) -> tuple[ReplyButton, ...]:
        """An item's decision buttons: Approve (signed) and See options."""
        out: list[ReplyButton] = []
        for button in item.buttons:
            if button.kind is ButtonKind.APPROVE and button.decision_id and button.option_id:
                approve = self._approve(conn, store_id, button.decision_id, button.option_id)
                if approve is not None:
                    out.append(approve)
            elif button.kind is ButtonKind.REVIEW and button.decision_id:
                out.append(ReplyButton(options_button(UUID(button.decision_id)), "See options"))
        return tuple(out)

    # --- business-initiated --------------------------------------------------------------

    def alert(self, conn: Connection, store_id: UUID, incident: Incident) -> WhatsAppMessage:
        document = alert_document(notice_context(conn, store_id, self.now), incident)
        text = _renderer(conn, store_id, document)
        why, step = _first(document, "why"), _first(document, "next_step")
        lines = [text(document.headline), text(why.text), text(step.text)]
        buttons = self._buttons(conn, store_id, step)
        data = incident.alert is AlertLevel.DATA_QUALITY or not buttons
        if data:
            lines[-1] += f" Evidence: {self._link(f'incidents/{incident.incident_id}')}"
        return WhatsAppMessage(
            text="\n".join([f"*{lines[0]}*", *lines[1:]]),
            buttons=buttons,
            footer=FOOTER,
            template=TEMPLATES["data" if data else "alert"],
            params=tuple(lines),
        )

    def brief(
        self, conn: Connection, store_id: UUID, content: BriefingContent, briefing_id: UUID
    ) -> WhatsAppMessage:
        text = _renderer(conn, store_id, content)
        title = briefing_title(content)
        if content.kind is not BriefingKind.DAILY:  # the reports are read on the web
            line = f"{text(content.headline)} Read it: {self._link(f'briefings/{briefing_id}')}"
            return WhatsAppMessage(
                text=f"*{title}*\n{line}",
                footer=FOOTER,
                template=TEMPLATES["brief"],
                params=(title, line, "-"),
            )
        health = text(_first(content, "health").text)
        top_items = _items(content, "top_items")
        top = top_items[0] if top_items else None
        top_line = f"Top: {text(top.text)}" if top else text(content.headline)
        buttons = self._buttons(conn, store_id, top) if top else ()
        return WhatsAppMessage(
            text=f"*{title}*\n{health}\n{top_line}",
            buttons=buttons,
            footer=FOOTER,
            template=TEMPLATES["brief"],
            params=(title, health, top_line),
        )

    def decision(self, conn: Connection, store_id: UUID, decision: DecisionView) -> WhatsAppMessage:
        ctx = notice_context(conn, store_id, self.now)
        if decision.status is DecisionStatus.PROPOSED:
            document = decision_document(ctx, decision)
            text = _renderer(conn, store_id, document)
            proposal = _first(document, "proposal")
            line = f"{text(document.headline)} {text(proposal.text)}"
            approve = self._approve(
                conn, store_id, str(decision.decision_id), decision.recommended_option_id
            )
            see = ReplyButton(options_button(decision.decision_id), "See options")
            buttons = (approve, see) if approve is not None else (see,)
            return WhatsAppMessage(
                text=line,
                buttons=buttons,
                footer=FOOTER,
                template=TEMPLATES["decision"],
                params=(line,),
            )
        option = decision.option(decision.approved_option_id or decision.recommended_option_id)
        words = STATUS_WORDS[decision.status].format(
            option=wording.option(option.kind), entity=entity_ref(ctx, decision.entity)
        )
        line = _renderer(conn, store_id, _cited(words))(words)
        return WhatsAppMessage(text=line, template=TEMPLATES["decision"], params=(line,))

    def goal(self, conn: Connection, store_id: UUID, goal_id: UUID) -> WhatsAppMessage | None:
        """The goal's weekly tracking line; None before its first week."""
        ctx = notice_context(conn, store_id, self.now)
        item = goal_item(ctx, goal_service.get(conn, store_id, goal_id))
        if item is None:
            return None
        line = _renderer(conn, store_id, _cited(item.text))(item.text)
        return WhatsAppMessage(
            text=f"*Goal progress*\n{line}",
            buttons=self._buttons(conn, store_id, item),
            footer=FOOTER,
            template=TEMPLATES["goal"],
            params=(line,),
        )

    # --- replies (the owner just wrote: the window is open) ----------------------------

    def answer(
        self, conn: Connection, store_id: UUID, result: AskResult, *, heard: str | None = None
    ) -> WhatsAppMessage:
        """Ask's answer; a goal restated comes with its "Confirm goal" button."""
        answer = result.answer
        texts = [answer.answer, answer.recommendation or ""]
        refs = set().union(*(fact_references(t) for t in texts))
        entities = set().union(*(entity_references(t) for t in texts))
        facts = get_facts(conn, store_id, sorted(refs))
        names = load_entity_names(conn, store_id, {"store", *entities})

        def text(value: str) -> str:
            return render(value, facts, names, Channel.WHATSAPP)

        lines = []
        if heard is not None:
            lines.append(f"_Heard:_ “{escape(heard, Channel.WHATSAPP, single_line=True)}”")
        lines.append(text(answer.answer))
        if answer.recommendation:
            lines.append(f"Next step: {text(answer.recommendation)}")
        if Flag.NO_INSTRUCTION_FOLLOWING_FROM_DATA in answer.flags:
            lines.append("_Instructions in a message are never followed: I answered the question._")
        buttons: tuple[ReplyButton, ...] = ()
        if result.status == "confirmation" and result.goal_id and self.secret is not None:
            token = goal_button(conn, store_id, result.goal_id, secret=self.secret, now=self.now)
            buttons = (ReplyButton(token, "Confirm goal"),)
        return WhatsAppMessage(text="\n".join(lines), buttons=buttons, footer=FOOTER)

    def options(self, conn: Connection, store_id: UUID, decision: DecisionView) -> WhatsAppMessage:
        """The decision's options with their simulated impact, and where to compare them."""
        document = decision_document(notice_context(conn, store_id, self.now), decision)
        text = _renderer(conn, store_id, document)
        lines = [f"- {text(i.text)}" for i in _items(document, "options")]
        lines.append(f"Compare them: {self._link(f'decisions/{decision.decision_id}')}")
        buttons: tuple[ReplyButton, ...] = ()
        if decision.status is DecisionStatus.PROPOSED:
            approve = self._approve(
                conn, store_id, str(decision.decision_id), decision.recommended_option_id
            )
            buttons = (approve,) if approve is not None else ()
        return WhatsAppMessage(text="\n".join(["*Options*", *lines]), buttons=buttons)

    def stale_button(self, decision_id: UUID | None = None) -> WhatsAppMessage:
        where = self._link(f"decisions/{decision_id}") if decision_id else self.app_base_url
        return WhatsAppMessage(
            text=f"That button has expired or was already used: nothing was decided. Open "
            f"Merit to decide: {where}"
        )

    def above_caps(self, decision_id: UUID) -> WhatsAppMessage:
        return WhatsAppMessage(
            text="This option goes beyond your spending caps, so it is approved on the web "
            f"only, after a confirmation: {self._link(f'decisions/{decision_id}')}"
        )

    def goal_confirmed(
        self, conn: Connection, store_id: UUID, result: AskResult
    ) -> WhatsAppMessage:
        """The confirmed goal's feasibility, explained (the plan is asked for on the web)."""
        message = self.answer(conn, store_id, result)
        return WhatsAppMessage(
            text=f"*Goal confirmed*\n{message.text}\nIts plan: {self._link('goals')}",
            footer=FOOTER,
        )


def help_message() -> WhatsAppMessage:
    return WhatsAppMessage(text=HELP)


def refusal_message() -> WhatsAppMessage:
    return WhatsAppMessage(text=REFUSAL)


def _items(document: Document, key: str) -> Sequence[Item]:
    return next((s.items for s in document.sections if s.key == key), ())


def _first(document: Document, key: str) -> Item:
    items = _items(document, key)
    if not items:
        raise LookupError(f"the document has no {key} section")
    return items[0]


def _cited(value: str) -> Document:
    """A one-line document citing what the text references."""
    return Document(
        headline=value,
        sections=(),
        fact_ids=tuple(sorted(fact_references(value))),
        entities=tuple(sorted(entity_references(value))),
    )


def _renderer(conn: Connection, store_id: UUID, document: Document) -> Callable[[str], str]:
    inputs = load_inputs(conn, store_id, document)
    return lambda value: render(value, inputs.facts, inputs.names, Channel.WHATSAPP)
