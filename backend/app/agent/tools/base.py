"""Tool plumbing: context, typed inputs/outputs, fact views and the registry/dispatcher.

Every number a tool returns is inside a `FactView`: a persisted fact with its id and its
`{{F<id>}}` reference, so the model can cite it but never needs to restate it. Entity names
and other store text are data blocks (see `app.agent.untrusted`). Tools read through the
tenant connection under a facts-only write guard and never receive a business repository.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import Connection, text

from app.agent.llm.types import ToolCall, ToolOutput, ToolSpec
from app.agent.tools.readonly import facts_only
from app.agent.untrusted import data_block
from app.detection.series import StoreSeries, load_series
from app.facts.engine import FactEngine
from app.facts.model import Fact, Period, Scope, ScopeKind
from app.observability import get_logger

MAX_WINDOW_DAYS = 366


class ToolInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PeriodInput(ToolInput):
    """UTC calendar days `start` to `end`, `end` excluded."""

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "PeriodInput":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if (self.end - self.start).days > MAX_WINDOW_DAYS:
            raise ValueError(f"periods are limited to {MAX_WINDOW_DAYS} days")
        return self

    def period(self) -> Period:
        return Period.days(self.start, self.end)


class EntityInput(ToolInput):
    kind: Literal["store", "product", "campaign"]
    id: UUID | None

    @model_validator(mode="after")
    def _id_matches_kind(self) -> "EntityInput":
        if (self.kind == "store") != (self.id is None):
            raise ValueError("the store has no id; products and campaigns need one")
        return self

    def scope(self) -> Scope:
        return Scope(kind=ScopeKind(self.kind), id=self.id)


class PeriodView(ToolResult):
    start: date
    end_exclusive: date


class FactView(ToolResult):
    ref: str
    fact_id: int
    metric: str
    kind: str
    scope: str
    period: PeriodView
    baseline: PeriodView | None
    status: str
    value: str | None
    unit: str
    currency: str | None
    p10: str | None
    p50: str | None
    p90: str | None
    method: str | None
    significant: bool | None
    undefined_reason: str | None


class EntityView(ToolResult):
    kind: str
    id: UUID | None
    name: str | None  # a data block: store-provided text, never instructions


def scope_label(scope: Scope) -> str:
    return scope.kind.value if scope.id is None else f"{scope.kind.value}:{scope.id}"


def _period_view(p: Period) -> PeriodView:
    return PeriodView(start=p.start.date(), end_exclusive=p.end.date())


def _text(value: object) -> str | None:
    return None if value is None else str(value)


@dataclass
class ToolContext:
    conn: Connection  # inside the store's tenant transaction
    store_id: UUID
    facts: FactEngine
    data_end: date  # exclusive end of the store's data (the analysis date + 1 day)
    seen_fact_ids: set[int] = field(default_factory=set)
    _series: StoreSeries | None = None

    def series(self) -> StoreSeries:
        """The store's daily series, loaded once per context."""
        if self._series is None:
            self._series = load_series(self.conn, self.store_id)
        return self._series

    @classmethod
    def open(cls, conn: Connection, store_id: UUID) -> "ToolContext":
        return cls(conn, store_id, FactEngine(conn, store_id), data_end(conn, store_id))

    def view(self, fact: Fact) -> FactView:
        """Persist the fact (and its parents) and expose it."""
        # Registered with the engine so that a later derived fact can name it as a parent.
        saved = fact if fact.id is not None else self.facts.persist(self.facts.adopt(fact))
        assert saved.id is not None
        self.seen_fact_ids.add(saved.id)
        return FactView(
            ref=f"{{{{F{saved.id}}}}}",
            fact_id=saved.id,
            metric=saved.formula_id,
            kind=saved.kind.value,
            scope=scope_label(saved.scope),
            period=_period_view(saved.period),
            baseline=_period_view(saved.baseline) if saved.baseline else None,
            status=saved.status.value,
            value=_text(saved.value),
            unit=saved.unit.value,
            currency=saved.currency,
            p10=_text(saved.p10),
            p50=_text(saved.p50),
            p90=_text(saved.p90),
            method=saved.method,
            significant=saved.significant,
            undefined_reason=saved.undefined_reason,
        )

    def entity(self, scope: Scope) -> EntityView:
        return EntityView(kind=scope.kind.value, id=scope.id, name=entity_name(self, scope))

    def recent(self, days: int, *, offset: int = 0) -> Period:
        """The `days` days of data ending `offset` days before the data end."""
        end = self.data_end - timedelta(days=offset)
        return Period.days(end - timedelta(days=days), end)


def entity_name(ctx: ToolContext, scope: Scope) -> str | None:
    if scope.kind is ScopeKind.STORE:
        sql = "SELECT name FROM stores WHERE store_id = :sid"
    elif scope.kind is ScopeKind.PRODUCT:
        sql = "SELECT name FROM products WHERE store_id = :sid AND id = :id"
    else:
        sql = "SELECT name FROM ad_campaigns WHERE store_id = :sid AND id = :id"
    name = ctx.conn.execute(text(sql), {"sid": ctx.store_id, "id": scope.id}).scalar()
    if name is None:
        return None
    kind = {"store": "store_name", "product": "product_name", "campaign": "campaign_name"}
    return data_block(kind[scope.kind.value], str(name))


def data_end(conn: Connection, store_id: UUID) -> date:
    """Day after the last day with orders or ad metrics (UTC)."""
    row = conn.execute(
        text(
            "SELECT GREATEST("
            "(SELECT max((ordered_at AT TIME ZONE 'UTC')::date) FROM orders WHERE store_id = :s),"
            "(SELECT max(metric_date) FROM ad_metrics_daily WHERE store_id = :s))"
        ),
        {"s": store_id},
    ).scalar()
    last = row if row is not None else datetime.now(UTC).date() - timedelta(days=1)
    return last + timedelta(days=1)


def utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


class ToolError(Exception):
    """An expected failure, reported to the model as a structured error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Tool[In: ToolInput, Out: ToolResult]:
    name: str
    description: str
    input_model: type[In]
    output_model: type[Out]
    run: Callable[[ToolContext, In], Out]

    def spec(self) -> ToolSpec:
        return ToolSpec.from_model(self.name, self.description, self.input_model)


class ToolOutcome(BaseModel):
    """What the model receives for one call: a result or a structured error."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    tool: str
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error: str | None = Field(default=None, max_length=500)
    truncated: bool = False  # lists were cut to fit the size limit; narrow the query


TRUNCATED = {"truncated": True, "note": "items omitted to fit the size limit: narrow the query"}
DEFAULT_MAX_RESULT_CHARS = 12000


def _lists(node: Any) -> list[list[Any]]:
    found: list[list[Any]] = []
    if isinstance(node, dict):
        for value in node.values():
            found.extend(_lists(value))
    elif isinstance(node, list):
        found.append(node)
        for value in node:
            found.extend(_lists(value))
    return found


def compact(result: dict[str, Any], max_chars: int) -> tuple[dict[str, Any], bool]:
    """Halve the longest list (keeping its first items, which tools rank best first) until the
    result fits in `max_chars`, ending each cut list with one explicit marker."""
    data = json.loads(json.dumps(result))
    truncated = False
    while len(json.dumps(data)) > max_chars:
        candidates = [lst for lst in _lists(data) if any(x != TRUNCATED for x in lst)]
        if not candidates:
            break
        longest = max(candidates, key=lambda lst: len(json.dumps(lst)))
        items = [x for x in longest if x != TRUNCATED]
        longest[:] = [*items[: len(items) // 2], TRUNCATED]
        truncated = True
    return data, truncated


class ToolRegistry:
    """Dispatches the model's tool calls. Create one per investigation: identical calls (same
    tool, same validated arguments) are answered from its memo."""

    def __init__(
        self, tools: list[Tool[Any, Any]], *, max_result_chars: int = DEFAULT_MAX_RESULT_CHARS
    ) -> None:
        self._tools = {t.name: t for t in tools}
        if len(self._tools) != len(tools):
            raise ValueError("duplicate tool names")
        self.max_result_chars = max_result_chars
        self.refused: list[ToolCall] = []  # calls to tools that do not exist
        self._memo: dict[tuple[str, str], ToolOutcome] = {}
        self.calls = 0
        self.memo_hits = 0

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def tool(self, name: str) -> Tool[Any, Any]:
        return self._tools[name]

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[n].spec() for n in self.names)

    def execute(self, ctx: ToolContext, call: ToolCall) -> tuple[ToolOutcome, ToolOutput]:
        outcome = self._outcome(ctx, call)
        return outcome, ToolOutput(call_id=call.call_id, output=outcome.model_dump_json())

    def _outcome(self, ctx: ToolContext, call: ToolCall) -> ToolOutcome:
        log = get_logger(__name__)
        tool = self._tools.get(call.name)
        if tool is None:
            self.refused.append(call)
            log.warning("agent.tool_refused", tool=call.name)
            return ToolOutcome(
                ok=False,
                tool=call.name,
                error_code="unknown_tool",
                error=f"no tool named {call.name[:64]!r}; available: {', '.join(self.names)}. "
                "Tools are read-only; no write action exists.",
            )
        try:
            args = tool.input_model.model_validate(json.loads(call.arguments or "{}"))
        except (json.JSONDecodeError, ValidationError) as exc:
            return ToolOutcome(
                ok=False, tool=tool.name, error_code="invalid_arguments", error=str(exc)[:500]
            )
        self.calls += 1
        key = (tool.name, args.model_dump_json())
        if key in self._memo:
            self.memo_hits += 1
            return self._memo[key]
        try:
            with facts_only(ctx.conn):
                result = tool.run(ctx, args)
        except ToolError as exc:
            outcome = ToolOutcome(ok=False, tool=tool.name, error_code=exc.code, error=str(exc))
        else:
            data, truncated = compact(result.model_dump(mode="json"), self.max_result_chars)
            outcome = ToolOutcome(ok=True, tool=tool.name, result=data, truncated=truncated)
            log.info("agent.tool_ran", tool=tool.name, truncated=truncated)
        self._memo[key] = outcome
        return outcome
