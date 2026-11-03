"""Conversations (migration 0027): the questions the owner asked, typed or said, and the answers
they got, the latest conversation first. Ask (`/ask/stream`, `/ask/voice`) starts one or
continues one; each answer is a turn. A turn's answer is the Ask answer contract, with the facts
and names it cites read again (facts never change).
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from app.api.auth import StoreDep
from app.api.deps import EngineDep
from app.api.pagination import Cursor, Limit, Page, decode_cursor, encode_cursor
from app.api.views import AskOut, ask_out
from app.conversations import store
from app.conversations.store import Summary, Topic
from app.db import tenant_transaction

router = APIRouter(prefix="/api/v1/stores/{store_id}/conversations", tags=["conversations"])
ConversationId = Annotated[UUID, Path()]


class ConversationSummary(BaseModel):
    conversation_id: UUID
    title: str  # its first question
    questions: int  # the answered ones
    created_at: datetime
    updated_at: datetime  # its latest answer


class TurnOut(BaseModel):
    turn_id: UUID
    position: int
    question: str  # as the owner asked it (said: its transcript)
    via: Literal["text", "voice"]
    topic: Topic | None  # the decision or the goal it was about
    asked_at: datetime
    answer: AskOut


class ConversationOut(ConversationSummary):
    turns: list[TurnOut]


def _summary(s: Summary) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=s.conversation_id,
        title=s.title,
        questions=s.questions,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.get("", response_model=Page[ConversationSummary])
def list_conversations(
    store_id: StoreDep, engine: EngineDep, limit: Limit = 50, cursor: Cursor = None
) -> Page[ConversationSummary]:
    """The store's conversations, the one answered last first."""
    before = None
    if cursor is not None:
        key = decode_cursor(cursor)
        try:
            before = (datetime.fromisoformat(key[0]), UUID(key[1]))
        except (IndexError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail={"code": "invalid_cursor", "message": "invalid cursor"}
            ) from exc
    with tenant_transaction(engine, store_id) as conn:
        found = store.listing(conn, store_id, limit=limit + 1, before=before)
    page = found[:limit]
    return Page[ConversationSummary](
        items=[_summary(s) for s in page],
        next_cursor=(
            encode_cursor([page[-1].updated_at.isoformat(), str(page[-1].conversation_id)])
            if len(found) > limit
            else None
        ),
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    store_id: StoreDep, conversation_id: ConversationId, engine: EngineDep
) -> ConversationOut:
    """A conversation, its questions and their answers in order."""
    with tenant_transaction(engine, store_id) as conn:
        found = store.read(conn, store_id, conversation_id)
        if found is None:
            raise HTTPException(
                status_code=404, detail={"code": "not_found", "message": "no such conversation"}
            )
        summary, turns = found
        out = [
            TurnOut(
                turn_id=t.turn_id,
                position=t.position,
                question=t.question,
                via=t.via,
                topic=t.topic,
                asked_at=t.created_at,
                answer=ask_out(conn, t.result),
            )
            for t in turns
        ]
    return ConversationOut(**_summary(summary).model_dump(), turns=out)
