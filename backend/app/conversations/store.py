"""Conversations and their turns (migration 0027).

A conversation is created when its first question is asked, titled by that question; each
answer Ask gives is kept as a turn, in order. A question about a decision or a goal carries it
(`Topic`): Ask reads it framed with the decision's or the goal's label, so the agent knows what
"this" is, and the turn keeps the question as the owner asked it. A conversation whose first
question got no answer has no turn and is not listed.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, func, insert, select, update

from app.agent.ask import AskResult
from app.domain.schema import conversation_turns, conversations, decisions, goals

TITLE_LENGTH = 120


class Topic(BaseModel):
    """What a question is about: a decision or a goal of the store, by the label the owner saw."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["decision", "goal"]
    id: UUID
    label: str = Field(min_length=1, max_length=200)


class ConversationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Summary:
    conversation_id: UUID
    title: str
    questions: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Turn:
    turn_id: UUID
    position: int
    question: str
    via: Literal["text", "voice"]
    topic: Topic | None
    result: AskResult
    created_at: datetime


def framed(question: str, topic: Topic | None) -> str:
    """The question as Ask reads it: about a decision or a goal, it names it first."""
    if topic is None:
        return question
    return f"About the {topic.kind} “{topic.label}”: {question}"


def title_of(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"


def check_topic(conn: Connection, store_id: UUID, topic: Topic) -> None:
    """The decision or the goal must be the store's."""
    table, key = (
        (decisions, decisions.c.decision_id)
        if topic.kind == "decision"
        else (goals, goals.c.goal_id)
    )
    found = conn.execute(
        select(func.count()).select_from(table).where(table.c.store_id == store_id, key == topic.id)
    ).scalar_one()
    if not found:
        raise ConversationError("invalid_topic", f"no {topic.kind} {topic.id} in this store")


def start(conn: Connection, store_id: UUID, question: str) -> UUID:
    conversation_id = uuid4()
    conn.execute(
        insert(conversations).values(
            conversation_id=conversation_id,
            store_id=store_id,
            title=title_of(question) or "Question",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    return conversation_id


def require(conn: Connection, store_id: UUID, conversation_id: UUID) -> None:
    found = conn.execute(
        select(conversations.c.conversation_id).where(
            conversations.c.store_id == store_id,
            conversations.c.conversation_id == conversation_id,
        )
    ).first()
    if found is None:
        raise ConversationError("not_found", f"no conversation {conversation_id}")


def append(
    conn: Connection,
    store_id: UUID,
    conversation_id: UUID,
    *,
    question: str,
    via: Literal["text", "voice"],
    topic: Topic | None,
    result: AskResult,
) -> int:
    """Keep an answer as the conversation's next turn; its position."""
    # The conversation's row is locked: two answers at once take the next positions in turn.
    conn.execute(
        select(conversations.c.conversation_id)
        .where(
            conversations.c.store_id == store_id,
            conversations.c.conversation_id == conversation_id,
        )
        .with_for_update()
    )
    position = (
        conn.execute(
            select(func.coalesce(func.max(conversation_turns.c.position), 0)).where(
                conversation_turns.c.store_id == store_id,
                conversation_turns.c.conversation_id == conversation_id,
            )
        ).scalar_one()
        + 1
    )
    conn.execute(
        insert(conversation_turns).values(
            turn_id=uuid4(),
            store_id=store_id,
            conversation_id=conversation_id,
            position=position,
            question=question.strip()[:2000],
            via=via,
            topic_kind=topic.kind if topic else None,
            topic_id=topic.id if topic else None,
            topic_label=topic.label if topic else None,
            ask_id=result.ask_id,
            result=result.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    conn.execute(
        update(conversations)
        .where(
            conversations.c.store_id == store_id,
            conversations.c.conversation_id == conversation_id,
        )
        .values(updated_at=datetime.now(UTC))
    )
    return int(position)


def _summaries(
    conn: Connection, store_id: UUID, *where: object, limit: int | None = None
) -> list[Summary]:
    count = func.count(conversation_turns.c.turn_id)
    query = (
        select(
            conversations.c.conversation_id,
            conversations.c.title,
            count.label("questions"),
            conversations.c.created_at,
            conversations.c.updated_at,
        )
        .join(
            conversation_turns,
            (conversation_turns.c.store_id == conversations.c.store_id)
            & (conversation_turns.c.conversation_id == conversations.c.conversation_id),
        )
        .where(conversations.c.store_id == store_id, *where)  # type: ignore[arg-type]
        .group_by(conversations.c.conversation_id)
        .order_by(conversations.c.updated_at.desc(), conversations.c.conversation_id.desc())
    )
    rows = conn.execute(query if limit is None else query.limit(limit)).all()
    return [Summary(r[0], r[1], int(r[2]), r[3], r[4]) for r in rows]


def listing(
    conn: Connection, store_id: UUID, *, limit: int, before: tuple[datetime, UUID] | None
) -> list[Summary]:
    """The conversations with at least one answer, the latest first; those after `before`."""
    where = []
    if before is not None:
        at, last = before
        where.append(
            (conversations.c.updated_at < at)
            | ((conversations.c.updated_at == at) & (conversations.c.conversation_id < last))
        )
    return _summaries(conn, store_id, *where, limit=limit)


def read(
    conn: Connection, store_id: UUID, conversation_id: UUID
) -> tuple[Summary, list[Turn]] | None:
    found = _summaries(conn, store_id, conversations.c.conversation_id == conversation_id)
    if not found:
        return None
    rows = conn.execute(
        select(conversation_turns)
        .where(
            conversation_turns.c.store_id == store_id,
            conversation_turns.c.conversation_id == conversation_id,
        )
        .order_by(conversation_turns.c.position)
    ).mappings()
    turns = [
        Turn(
            turn_id=r["turn_id"],
            position=r["position"],
            question=r["question"],
            via=r["via"],
            topic=(
                Topic(kind=r["topic_kind"], id=r["topic_id"], label=r["topic_label"])
                if r["topic_kind"]
                else None
            ),
            result=AskResult.model_validate(r["result"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return found[0], turns
