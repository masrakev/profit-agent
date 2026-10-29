"""Ask: answer the owner's question with the answer contract (Task 3 Part B2, SPEC section 8).

1. Classify the question into a SPEC section 8 type (classification stage; the Contributor model
   on synthetic stores, Spark otherwise).
2. `out_of_scope` gets a deterministic scope statement; `evaluate`, `what_if` and `review` need the
   simulation and decisions modules and get a structured `not_available_yet` answer.
3. Other types run the shared agent loop (lookup stage) with every read-only tool, and the answer
   is verified like any model output, plus checks enforced in code: a recommendation states what
   would change the mind; a diagnosis lists alternatives and ranked causes (unless nothing
   material is wrong); a data-quality issue never leads to pausing a campaign; the answer never
   claims an action was taken. Store text that looked like an instruction adds the flag
   `no_instruction_following_from_data`.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.agent.contracts import ActionFamily, Answer, Flag, fallback_answer
from app.agent.guard import OutputViolation
from app.agent.investigator import store_context
from app.agent.llm.errors import LLMError
from app.agent.llm.models import DataOrigin
from app.agent.llm.provider import LLMProvider
from app.agent.llm.types import LLMRequest, LLMResult, UserMessage
from app.agent.origin import data_origin
from app.agent.prompts import load_prompt
from app.agent.session import UsageSummary, run_session, summarize
from app.agent.stages import Routing, Stage, StagesConfig, load_stages
from app.agent.tools import ToolContext, build_registry
from app.db import tenant_transaction
from app.observability import get_logger


class QuestionType(StrEnum):
    LOOKUP = "lookup"
    EXPLAIN = "explain"
    DIAGNOSE = "diagnose"
    IMPROVE = "improve"
    EVALUATE = "evaluate"
    WHAT_IF = "what_if"
    REVIEW = "review"
    DATA_QUESTION = "data_question"
    OUT_OF_SCOPE = "out_of_scope"


NOT_AVAILABLE_YET = frozenset({QuestionType.EVALUATE, QuestionType.WHAT_IF, QuestionType.REVIEW})
ACTION_CLAIM = re.compile(
    r"(?i)\b(?:i|we)\s+(?:have\s+)?(?:paused|stopped|increased|reduced|raised|lowered|changed|"
    r"launched|updated|cut|doubled|moved|deleted|bought|ordered)\b"
)
PAUSE_WORDS = re.compile(r"(?i)\b(?:pause|stop|turn\s+off|cut|switch\s+off|kill)\b")
CUTTING_ACTIONS = (ActionFamily.PAUSE_OR_REDUCE_CAMPAIGN, ActionFamily.REDUCE_OR_REALLOCATE_BUDGET)


class Classification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question_type: QuestionType


AskStatus = Literal["answered", "fallback", "partial", "not_available_yet", "out_of_scope"]


class AskResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ask_id: UUID
    store_id: UUID
    question: str
    question_type: QuestionType | None
    status: AskStatus
    answer: Answer
    model: str | None
    classification_model: str
    prompt_version: str
    usage: UsageSummary
    classification_usage: UsageSummary
    tool_calls: int
    memo_hits: int
    regenerations: int
    verifier_violations: int
    refused_tools: list[str]
    stop_reason: str | None
    created_at: datetime


def out_of_scope_answer() -> Answer:
    return Answer(
        answer="This question is outside what your store's data can answer: I work from your "
        "sales, costs, ads and stock.",
        evidence=[],
        reasoning=None,
        alternatives=[],
        uncertainty="Nothing in the store's data bears on this question.",
        recommendation=None,
        would_change_my_mind=None,
        flags=[Flag.OUT_OF_SCOPE],
    )


def not_available_answer(question_type: QuestionType) -> Answer:
    if question_type is QuestionType.REVIEW:
        needs = "decisions and measured outcomes"
    else:
        needs = "the simulation module"
    return Answer(
        answer=f"Answering a {question_type.value.replace('_', '-')} question needs {needs}, "
        "which is not available yet.",
        evidence=[],
        reasoning=None,
        alternatives=[],
        uncertainty="No simulated or measured outcome exists yet for this kind of question.",
        recommendation=None,
        would_change_my_mind=None,
        flags=[Flag.ABSTAIN_INSUFFICIENT_EVIDENCE],
    )


CheckFn = Callable[[Answer], list[OutputViolation]]


def contract_checks(question_type: QuestionType) -> CheckFn:
    def check(answer: Answer) -> list[OutputViolation]:
        found: list[OutputViolation] = []
        abstained = {Flag.ABSTAIN_INSUFFICIENT_EVIDENCE, Flag.NO_MATERIAL_ISSUE} & set(answer.flags)
        if answer.recommendation and not answer.would_change_my_mind:
            found.append(
                OutputViolation("would_change_my_mind", "contract", "say what would change it")
            )
        if not answer.evidence and not abstained:
            found.append(OutputViolation("evidence", "contract", "cite the facts you used"))
        if question_type is QuestionType.DIAGNOSE and not abstained:
            if not answer.alternatives:
                found.append(OutputViolation("alternatives", "contract", "list the alternatives"))
            if not answer.ranked_causes:
                found.append(OutputViolation("ranked_causes", "contract", "rank the causes"))
        cuts = answer.action_family in CUTTING_ACTIONS or PAUSE_WORDS.search(
            answer.recommendation or ""
        )
        if Flag.DATA_QUALITY in answer.flags and cuts:
            found.append(
                OutputViolation(
                    "recommendation", "safety", "never pause or cut over a data-quality issue"
                )
            )
        texts = (answer.answer, answer.reasoning or "", answer.recommendation or "")
        if any(ACTION_CLAIM.search(t) for t in texts):
            found.append(OutputViolation("answer", "safety", "you cannot act: claim no action"))
        return found

    return check


def classification_routing(origin: DataOrigin) -> Routing:
    """SPEC section 16: classification uses the Contributor model on synthetic stores."""
    return Routing.ECONOMY if origin is DataOrigin.SYNTHETIC else Routing.PRODUCTION


def ask(
    engine: Engine,
    store_id: UUID,
    question: str,
    provider: LLMProvider,
    *,
    routing: Routing = Routing.PRODUCTION,
    stages: StagesConfig | None = None,
    run_id: str | None = None,
) -> AskResult:
    stages = stages or load_stages()
    classify, answer_prompt = load_prompt("classify"), load_prompt("ask")
    ask_id = uuid4()
    log = get_logger(__name__)
    question = question.strip()[:2000]
    with tenant_transaction(engine, store_id) as conn:
        origin = data_origin(conn, store_id)
        cls_route = stages.route(
            Stage.CLASSIFICATION, origin, classification_routing(origin), "classification"
        )
        cls_results: list[LLMResult] = []
        question_type: QuestionType | None = None
        try:
            result = provider.generate(
                LLMRequest(
                    model=cls_route.model,
                    data_origin=origin,
                    instructions=classify.text,
                    prompt_version=classify.version,
                    input=(UserMessage(text=question),),
                    output_schema=Classification,
                    reasoning_effort=cls_route.reasoning_effort,
                    max_output_tokens=stages[Stage.CLASSIFICATION].max_output_tokens,
                    run_id=run_id or str(ask_id),
                    purpose=Stage.CLASSIFICATION.value,
                    store_id=store_id,
                )
            )
            cls_results.append(result)
            if isinstance(result.parsed, Classification):
                question_type = result.parsed.question_type
        except LLMError as exc:
            log.warning("agent.classification_failed", error=type(exc).__name__)
        common: dict[str, Any] = {
            "ask_id": ask_id,
            "store_id": store_id,
            "question": question,
            "question_type": question_type,
            "classification_model": cls_route.model.value,
            "prompt_version": f"{classify.version}:{answer_prompt.version}",
            "classification_usage": summarize(cls_results),
            "created_at": datetime.now(UTC),
        }
        no_answer_run: dict[str, Any] = {
            "model": None,
            "usage": UsageSummary(),
            "tool_calls": 0,
            "memo_hits": 0,
            "regenerations": 0,
            "verifier_violations": 0,
            "refused_tools": [],
        }
        if question_type is None:
            answer = fallback_answer([], reason="the question could not be classified")
            return AskResult(
                **common,
                **no_answer_run,
                status="partial",
                answer=answer,
                stop_reason="classification failed",
            )
        if question_type is QuestionType.OUT_OF_SCOPE:
            return AskResult(
                **common,
                **no_answer_run,
                status="out_of_scope",
                answer=out_of_scope_answer(),
                stop_reason=None,
            )
        if question_type in NOT_AVAILABLE_YET:
            return AskResult(
                **common,
                **no_answer_run,
                status="not_available_yet",
                answer=not_available_answer(question_type),
                stop_reason=None,
            )
        route = stages.route(Stage.LOOKUP, origin, routing, f"{question_type.value} question")
        cfg = stages[Stage.LOOKUP]
        ctx = ToolContext.open(conn, store_id)
        registry = build_registry(stages.max_result_chars)
        question_message = UserMessage(
            text=f"Question type: {question_type.value}\nOwner's question: {question}"
        )
        run = run_session(
            provider,
            registry,
            ctx,
            LLMRequest(
                model=route.model,
                data_origin=origin,
                instructions=answer_prompt.text,
                prompt_version=answer_prompt.version,
                input=(store_context(conn, ctx), question_message),
                reasoning_effort=route.reasoning_effort,
                max_output_tokens=cfg.max_output_tokens,
                run_id=run_id or str(ask_id),
                purpose=f"ask-{question_type.value}",
                store_id=store_id,
            ),
            Answer,
            max_tool_calls=cfg.max_tool_calls,
            max_input_tokens=cfg.max_input_tokens,
            extra_entities={"store"},
            validate=contract_checks(question_type),
        )
        if run.output is not None:
            status: AskStatus = "answered"
            answer = run.output
        else:
            status = "partial" if run.stopped_by_budget else "fallback"
            reason = run.stop_reason or "its answer could not be verified"
            answer = fallback_answer(sorted(ctx.seen_fact_ids)[:5], reason=reason)
        if ctx.suspicious_entities and Flag.NO_INSTRUCTION_FOLLOWING_FROM_DATA not in answer.flags:
            flags = [*answer.flags, Flag.NO_INSTRUCTION_FOLLOWING_FROM_DATA]
            answer = answer.model_copy(update={"flags": flags})
    usage = run.usage()
    log.info("agent.asked", type=question_type.value, status=status, cost_usd=str(usage.cost_usd))
    return AskResult(
        **common,
        status=status,
        answer=answer,
        model=route.model.value,
        usage=usage,
        tool_calls=run.tool_calls,
        memo_hits=registry.memo_hits,
        regenerations=run.regenerations,
        verifier_violations=run.violations,
        refused_tools=[c.name for c in registry.refused],
        stop_reason=run.stop_reason,
    )
