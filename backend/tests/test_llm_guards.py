"""Budget guard, spend ledgers, circuit breaker, price table and strict JSON schemas."""

import threading
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel, RootModel

from app.agent.llm import BudgetCaps, BudgetExceededError, CircuitOpenError, ModelId, Usage
from app.agent.llm import fake as f
from app.agent.llm.budget import BudgetGuard, InMemorySpendLedger, JsonlSpendLedger
from app.agent.llm.errors import ProviderUnavailableError
from app.agent.llm.models import PRICES_FILE, load_prices
from app.agent.llm.resilience import BreakerState, CircuitBreaker
from app.agent.llm.schema import SchemaError, strict_schema
from tests.llm_helpers import Clock, Harness, request

D = Decimal


# --- budget --------------------------------------------------------------------------------


def test_budget_refuses_the_call_that_could_exceed_the_run_cap() -> None:
    # Worst case of the default request: ~550 body bytes as input tokens + 4096 output tokens
    # at Spark prices is about 0.018 USD.
    h = Harness(
        [f.ok([f.message("a")]), f.ok([f.message("b")])],
        caps=BudgetCaps(per_run_usd=D("0.03"), daily_usd=D("1")),
    )
    h.provider.generate(request(run_id="r1"))
    spent = h.guard.spent("r1").run
    assert spent == D("0.00021")  # the reservation was settled to the actual cost
    h.provider.generate(request(run_id="r1"))
    with pytest.raises(BudgetExceededError, match="per-run"):
        h.provider.generate(request(run_id="r1", max_output_tokens=8000))
    assert len(h.transport.requests) == 2  # the third call never left the process
    assert h.guard.spent("r1").run == D("0.00042")


def test_daily_and_total_caps() -> None:
    days = iter([date(2026, 10, 28)] * 2 + [date(2026, 10, 29)] * 2)
    guard = BudgetGuard(
        BudgetCaps(per_run_usd=D("10"), daily_usd=D("1.00"), total_usd=D("1.50")),
        InMemorySpendLedger(),
        today=lambda: next(days),
    )
    r = guard.reserve("a", "m", D("0.80"))
    guard.settle(r, D("0.80"))
    with pytest.raises(BudgetExceededError, match="daily"):
        guard.reserve("b", "m", D("0.30"))  # same day: 0.80 + 0.30 > 1.00
    r = guard.reserve("b", "m", D("0.60"))  # next day
    guard.settle(r, D("0.60"))
    with pytest.raises(BudgetExceededError, match="total"):
        guard.reserve("c", "m", D("0.20"))  # 1.40 + 0.20 > 1.50 overall


def test_unsettled_reservations_stay_counted() -> None:
    guard = BudgetGuard(BudgetCaps(D("1"), D("1")), InMemorySpendLedger())
    guard.reserve("a", "m", D("0.70"))  # e.g. the process died during the call
    with pytest.raises(BudgetExceededError):
        guard.reserve("a", "m", D("0.40"))


def test_jsonl_ledger_is_shared_and_locked(tmp_path: Path) -> None:
    path = tmp_path / "spend.jsonl"
    caps = BudgetCaps(D("10"), D("1.00"))
    first = BudgetGuard(caps, JsonlSpendLedger(path))
    second = BudgetGuard(caps, JsonlSpendLedger(path))  # another process, same file
    r = first.reserve("run", "muse-spark-1.3", D("0.40"))
    first.settle(r, D("0.25"))
    assert second.spent("run").day == D("0.25")
    errors: list[Exception] = []

    def reserve() -> None:
        try:
            second.reserve("run", "muse-spark-1.3", D("0.30"))
        except BudgetExceededError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reserve) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 0.25 + 2 x 0.30 fits under 1.00; the 18 other concurrent reservations are refused.
    assert len(errors) == 18
    assert first.spent("run").day == D("0.85")
    lock = path.with_suffix(".jsonl.lock")
    lock.write_text("held")
    stuck = BudgetGuard(caps, JsonlSpendLedger(path, lock_timeout=0.05))
    with pytest.raises(TimeoutError):
        stuck.spent("run")


# --- circuit breaker -----------------------------------------------------------------------


def test_circuit_opens_after_repeated_failures_and_recovers() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=3, cooldown=30, clock=clock)
    h = Harness(
        [f.overloaded()] * 3 + [f.ok([f.message("back")])] * 2, breaker=breaker, max_attempts=3
    )
    with pytest.raises(ProviderUnavailableError):
        h.provider.generate(request())
    assert breaker.state is BreakerState.OPEN
    with pytest.raises(CircuitOpenError):
        h.provider.generate(request())
    assert len(h.transport.requests) == 3  # the open circuit made no request
    clock.now = 31
    assert breaker.state is BreakerState.HALF_OPEN
    assert h.provider.generate(request()).text == "back"  # the trial call closes it
    assert breaker.state is BreakerState.CLOSED


def test_failed_trial_reopens_the_circuit() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown=10, clock=clock)
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    clock.now = 10
    breaker.before_call()  # the single trial
    with pytest.raises(CircuitOpenError):
        breaker.before_call()  # no second concurrent trial
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    clock.now = 25
    breaker.before_call()
    breaker.record_success()
    assert breaker.state is BreakerState.CLOSED


def test_gateway_timeouts_count_against_the_circuit() -> None:
    breaker = CircuitBreaker(failure_threshold=1, clock=Clock())
    h = Harness([f.error(504, "server_error", "slow", code="gateway_timeout")], breaker=breaker)
    with pytest.raises(Exception, match="504"):
        h.provider.generate(request())
    assert breaker.state is BreakerState.OPEN


# --- prices --------------------------------------------------------------------------------


def test_price_table_matches_the_published_prices() -> None:
    table = load_prices()
    assert (table.version, table.verified_on) == (1, date(2026, 10, 28))
    expected = {
        ModelId.SPARK: ("1.25", "0.15", "4.25"),
        ModelId.SPARK_CONTRIBUTOR: ("0.10", "0.002", "0.20"),
        ModelId.WONDER: ("4.00", "0.20", "20.00"),
    }
    for model, (inp, cached, out) in expected.items():
        p = table.price(model)
        assert (p.input, p.cached_input, p.output) == (D(inp), D(cached), D(out))


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # 1,000,000 input of which 200,000 cached, 100,000 output (reasoning included).
        (ModelId.SPARK, D("1.455")),  # 0.8 x 1.25 + 0.2 x 0.15 + 0.1 x 4.25
        (ModelId.SPARK_CONTRIBUTOR, D("0.1004")),  # 0.8 x 0.10 + 0.2 x 0.002 + 0.1 x 0.20
        (ModelId.WONDER, D("5.24")),  # 0.8 x 4.00 + 0.2 x 0.20 + 0.1 x 20.00
    ],
)
def test_cost_golden(model: ModelId, expected: Decimal) -> None:
    usage = Usage(1_000_000, 200_000, 100_000, 60_000)
    assert load_prices().cost(model, usage) == expected
    assert load_prices().upper_bound(model, 1_000_000, 100_000) >= expected


def test_usage_adds_up() -> None:
    assert Usage(1, 2, 3, 4) + Usage(10, 20, 30, 40) == Usage(11, 22, 33, 44)


def test_inconsistent_price_tables_are_rejected(tmp_path: Path) -> None:
    text = PRICES_FILE.read_text(encoding="utf-8")
    wrong_mode = tmp_path / "mode.toml"
    wrong_mode.write_text(text.replace('mode = "contributor"', 'mode = "standard"'))
    with pytest.raises(ValueError, match="disagrees"):
        load_prices.__wrapped__(wrong_mode)
    missing = tmp_path / "missing.toml"
    missing.write_text(text.split("[models.muse-wonder-1_0]")[0])
    with pytest.raises(ValueError, match="misses"):
        load_prices.__wrapped__(missing)


# --- strict schemas ------------------------------------------------------------------------


class Confidence(StrEnum):
    HIGH = "high"
    LOW = "low"


class Evidence(BaseModel):
    fact_id: int
    role: str = "support"


class Hypothesis(BaseModel):
    """A ranked hypothesis."""

    family: str
    confidence: Confidence
    evidence: list[Evidence]
    counter: Evidence | None = None


class Investigation(BaseModel):
    hypotheses: list[Hypothesis]
    narrative: str


def _objects(node: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for value in node.values():
            found.extend(_objects(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_objects(value))
    return found


def test_strict_schema_meets_the_strict_subset() -> None:
    schema = strict_schema(Investigation)
    text = str(schema)
    assert "$ref" not in text
    assert "$defs" not in text
    assert "title" not in text
    assert "default" not in text
    objects = _objects(schema)
    assert len(objects) >= 3
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])  # type: ignore[call-overload]
    hypothesis = schema["properties"]["hypotheses"]["items"]
    assert hypothesis["properties"]["confidence"] == {"enum": ["high", "low"], "type": "string"}
    assert {"type": "null"} in hypothesis["properties"]["counter"]["anyOf"]


class Node(BaseModel):
    children: list["Node"]


class Loose(BaseModel):
    extra: dict[str, int]


def test_unsupported_schemas_are_rejected() -> None:
    with pytest.raises(SchemaError, match="recursive"):
        strict_schema(Node)
    with pytest.raises(SchemaError, match="free-form"):
        strict_schema(Loose)
    with pytest.raises(ValueError, match="free-form"):
        request(output_schema=Loose)


def test_schema_rewrite_edge_cases() -> None:
    from app.agent.llm.schema import _rewrite

    defs = {"A": {"type": "object", "properties": {"x": {"type": "integer"}}}}
    assert _rewrite({"oneOf": [{"type": "string"}, {"type": "null"}]}, defs, depth=0, seen=()) == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    wrapped = _rewrite(
        {"allOf": [{"$ref": "#/$defs/A"}], "description": "d"}, defs, depth=0, seen=()
    )
    assert wrapped["required"] == ["x"]
    assert wrapped["description"] == "d"
    with pytest.raises(SchemaError, match="allOf"):
        _rewrite({"allOf": [{"type": "string"}, {"type": "integer"}]}, defs, depth=0, seen=())
    with pytest.raises(SchemaError, match="unknown reference"):
        _rewrite({"$ref": "#/$defs/B"}, defs, depth=0, seen=())
    with pytest.raises(SchemaError, match="deeper"):
        _rewrite({"type": "string"}, defs, depth=31, seen=())

    with pytest.raises(SchemaError, match="root"):
        strict_schema(RootModel[list[int]])


def test_lock_file_being_deleted_counts_as_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seen on Windows under load: while one holder deletes the lock file, another's O_EXCL open
    # raises PermissionError ("delete pending") instead of FileExistsError.
    import app.agent.llm.budget as budget

    real_open = budget.os.open
    calls = {"n": 0}

    def flaky_open(path: str, flags: int, *args: int) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "Permission denied", path)
        return real_open(path, flags, *args)

    monkeypatch.setattr(budget.os, "open", flaky_open)
    guard = BudgetGuard(BudgetCaps(D("1"), D("1")), JsonlSpendLedger(tmp_path / "s.jsonl"))
    assert guard.spent("run").day == 0
    assert calls["n"] == 2  # waited, then took the lock
