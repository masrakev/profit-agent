"""Read-only agent tools on a golden scenario (stockout on a promoted product)."""

import ast
import json
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, insert, text

from app.agent.llm.types import ToolCall
from app.agent.tools import TOOLS, ToolContext, build_registry
from app.agent.tools.base import TRUNCATED, PeriodInput, Tool, ToolInput, ToolResult
from app.agent.tools.readonly import WriteForbiddenError, facts_only
from app.agent.untrusted import CLOSE, OPEN
from app.db import tenant_transaction
from app.domain.schema import products
from app.facts.repository import get_facts

pytestmark = pytest.mark.db
TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "agent" / "tools"


@pytest.fixture
def store(golden_stockout: dict[str, Any]) -> dict[str, Any]:
    return golden_stockout


@pytest.fixture
def ctx(app_engine: Engine, store: dict[str, Any]) -> Iterator[ToolContext]:
    with tenant_transaction(app_engine, store["id"]) as conn:
        yield ToolContext.open(conn, store["id"])


def call(ctx: ToolContext, name: str, **arguments: Any) -> dict[str, Any]:
    registry = build_registry()
    outcome, output = registry.execute(
        ctx, ToolCall("c1", name, json.dumps(arguments, default=str))
    )
    assert json.loads(output.output) == json.loads(outcome.model_dump_json())
    assert outcome.ok, outcome.error
    assert outcome.result is not None
    return outcome.result


def error(ctx: ToolContext, name: str, arguments: str | dict[str, Any]) -> str:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments, default=str)
    outcome, _ = build_registry().execute(ctx, ToolCall("c1", name, raw))
    assert not outcome.ok
    assert outcome.error_code is not None
    return outcome.error_code


def fact_views(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        found = [node] if "fact_id" in node and "ref" in node else []
        return found + [v for value in node.values() for v in fact_views(value)]
    if isinstance(node, list):
        return [v for value in node for v in fact_views(value)]
    return []


def numbers_outside_facts(node: Any, inside: bool = False) -> list[Any]:
    """Numeric JSON values that are not part of a fact view (tool outputs must have none)."""
    if isinstance(node, dict):
        is_fact = "fact_id" in node and "ref" in node
        return [
            n
            for k, v in node.items()
            for n in numbers_outside_facts(v, inside or is_fact)
            if not (k == "id" and isinstance(v, str))
        ]
    if isinstance(node, list):
        return [n for v in node for n in numbers_outside_facts(v, inside)]
    if isinstance(node, bool) or node is None or isinstance(node, str):
        return []
    return [] if inside else [node]


def test_registry_lists_the_typed_tools() -> None:
    registry = build_registry()
    assert registry.names == sorted(
        [
            "compare_entities",
            "compute",
            "get_campaign_context",
            "get_data_quality",
            "get_facts",
            "get_incident",
            "list_incidents",
            "list_products",
            "get_inventory_context",
            "get_profit_bridge",
            "get_series_summary",
            "run_sensitivity",
            "check_reconciliation",
            "get_method",
        ]
    )
    for spec in registry.specs():
        assert spec.parameters["type"] == "object"
        assert spec.parameters["additionalProperties"] is False
    with pytest.raises(ValueError, match="duplicate"):
        type(registry)([TOOLS[0], TOOLS[0]])


def test_get_incident(ctx: ToolContext, store: dict[str, Any]) -> None:
    view = call(ctx, "get_incident", incident_id=store["incident"])
    assert view["incident_id"] == store["incident"]
    assert view["candidates"][0]["family"] == "stockout_on_promoted"
    assert view["expected_monthly_impact"]["kind"] == "estimate"
    facts = fact_views(view)
    assert facts
    assert all(f["ref"] == f"{{{{F{f['fact_id']}}}}}" for f in facts)
    assert {f["fact_id"] for f in facts} <= ctx.seen_fact_ids
    assert numbers_outside_facts(view) == []
    names = [e["name"] for e in view["entities"] if e["name"]]
    assert names
    assert all(
        n.startswith(f"{OPEN}data kind=") and n.endswith(f"{OPEN}/data{CLOSE}") for n in names
    )
    assert error(ctx, "get_incident", {"incident_id": "inc-000000000000"}) == "not_found"
    assert error(ctx, "get_incident", {"incident_id": "DROP TABLE"}) == "invalid_arguments"


def test_get_profit_bridge_reconciles(ctx: ToolContext, store: dict[str, Any]) -> None:
    end = ctx.data_end
    current = {"start": end - timedelta(days=28), "end": end}
    baseline = {"start": end - timedelta(days=56), "end": end - timedelta(days=28)}
    view = call(
        ctx,
        "get_profit_bridge",
        scope={"kind": "store", "id": None},
        baseline=baseline,
        current=current,
    )
    total = sum(Decimal(d["contribution"]["value"]) for d in view["drivers"])
    assert total == Decimal(view["net_profit_change"]["value"])  # exact Shapley efficiency
    assert {d["driver"] for d in view["drivers"]} >= {"volume", "ad_spend", "unit_cost"}
    assert any(d["significant"] is not None for d in view["drivers"])
    product = str(store["product"])
    one = call(
        ctx,
        "get_profit_bridge",
        scope={"kind": "product", "id": product},
        baseline=baseline,
        current=current,
    )
    scopes = {f["scope"] for e in one["entity_contributions"] for f in e["contributions"]}
    assert scopes <= {f"product:{product}"}
    assert error(
        ctx,
        "get_profit_bridge",
        {"scope": {"kind": "store", "id": None}, "baseline": current, "current": baseline},
    ) == ("invalid_periods")
    assert numbers_outside_facts(view) == []


def test_get_facts_and_compare(ctx: ToolContext, store: dict[str, Any]) -> None:
    period = {"start": ctx.data_end - timedelta(days=28), "end": ctx.data_end}
    fact = call(
        ctx, "get_facts", metric="net_profit", scope={"kind": "store", "id": None}, period=period
    )["fact"]
    assert (fact["metric"], fact["unit"], fact["kind"]) == ("net_profit", "money", "exact")
    assert (
        error(
            ctx,
            "get_facts",
            {"metric": "made_up", "scope": {"kind": "store", "id": None}, "period": period},
        )
        == "unknown_metric"
    )
    assert (
        error(
            ctx,
            "get_facts",
            {
                "metric": "net_profit",
                "period": period,
                "scope": {"kind": "product", "id": str(store["product"])},
            },
        )
        == "unsupported_scope"
    )
    assert error(
        ctx,
        "get_facts",
        {
            "metric": "units",
            "scope": {"kind": "store", "id": None},
            "period": {"start": "2026-02-01", "end": "2026-01-01"},
        },
    ) == ("invalid_arguments")
    entities = [{"kind": "product", "id": str(p)} for p in store["products"][:5]]
    compared = call(ctx, "compare_entities", metric="units", entities=entities, period=period)
    values = [Decimal(i["fact"]["value"]) for i in compared["items"]]
    assert values == sorted(values, reverse=True)
    assert numbers_outside_facts(compared) == []


def test_get_series_summary(ctx: ToolContext, store: dict[str, Any]) -> None:
    fault = store["fault_day"]
    window = {"start": fault - timedelta(days=28), "end": fault + timedelta(days=28)}
    view = call(
        ctx,
        "get_series_summary",
        metric="units",
        entity={"kind": "product", "id": str(store["product"])},
        window=window,
    )
    first, last, change = view["first_day"], view["last_day"], view["change"]
    assert Decimal(change["value"]) == Decimal(last["value"]) - Decimal(first["value"])
    slope = view["slope_per_day"]
    assert slope["kind"] == "estimate"
    assert Decimal(slope["p10"]) <= Decimal(slope["p50"]) <= Decimal(slope["p90"])
    # A stockout on a promoted product: daily units step down, the change point is found.
    assert view["change_point"] is not None
    assert Decimal(view["mean_after"]["value"]) < Decimal(view["mean_before"]["value"])
    with_lineage = get_facts(ctx.conn, ctx.store_id, [change["fact_id"]], with_lineage=True)
    assert [p.role for p in with_lineage[change["fact_id"]].lineage.parents] == ["start", "end"]
    assert (
        error(
            ctx,
            "get_series_summary",
            {
                "metric": "inventory_cover_days",
                "entity": {"kind": "product", "id": str(store["product"])},
                "window": window,
            },
        )
        == "unknown_metric"
    )
    short = {"start": ctx.data_end - timedelta(days=2), "end": ctx.data_end}
    assert (
        error(
            ctx,
            "get_series_summary",
            {"metric": "units", "entity": {"kind": "store", "id": None}, "window": short},
        )
        == "invalid_window"
    )
    assert numbers_outside_facts(view) == []


def test_campaign_inventory_and_data_quality(ctx: ToolContext, store: dict[str, Any]) -> None:
    campaign = call(ctx, "get_campaign_context", campaign_id=str(store["campaign"]))
    assert campaign["campaign"]["name"].startswith(f"{OPEN}data kind=campaign_name")
    assert {f["metric"] for f in campaign["recent"]} >= {"ad_spend", "clicks", "attribution_ratio"}
    assert campaign["clicks_trend"]["first_day"]["metric"] == "clicks"
    assert error(ctx, "get_campaign_context", {"campaign_id": str(uuid4())}) == "not_found"
    inventory = call(ctx, "get_inventory_context", product_id=str(store["product"]))
    assert inventory["units_on_hand"]["metric"] == "units_on_hand"
    assert inventory["supplier_lead_time_days"]["status"] == "defined"
    assert inventory["promoted_by"]
    assert error(ctx, "get_inventory_context", {"product_id": str(uuid4())}) == "not_found"
    quality = call(ctx, "get_data_quality")
    assert {s["source"]: s["status"] for s in quality["sources"]} == {
        "orders": "fresh",
        "ad_metrics": "fresh",
        "inventory": "fresh",
    }
    assert len(quality["reconciliation"]) >= 1
    for view in (campaign, inventory, quality):
        assert numbers_outside_facts(view) == []


def test_compute_derives_exact_facts_from_seen_facts(ctx: ToolContext) -> None:
    period = {"start": ctx.data_end - timedelta(days=28), "end": ctx.data_end}
    store_scope = {"kind": "store", "id": None}
    revenue = call(ctx, "get_facts", metric="revenue", scope=store_scope, period=period)["fact"]
    cogs = call(ctx, "get_facts", metric="cogs", scope=store_scope, period=period)["fact"]
    units = call(ctx, "get_facts", metric="units", scope=store_scope, period=period)["fact"]
    r, c, u = revenue["fact_id"], cogs["fact_id"], units["fact_id"]
    margin = call(ctx, "compute", expression=f"F{r} - F{c}", fact_ids=[r, c])["fact"]
    assert Decimal(margin["value"]) == Decimal(revenue["value"]) - Decimal(cogs["value"])
    assert (margin["metric"], margin["kind"], margin["unit"]) == (
        "derived.compute",
        "exact",
        "money",
    )
    rate = call(ctx, "compute", expression=f"({{{{F{r}}}}} - F{c}) / F{r}", fact_ids=[r, c])
    assert rate["fact"]["unit"] == "ratio"
    per_unit = call(ctx, "compute", expression=f"F{r} / F{u}", fact_ids=[r, u])["fact"]
    assert per_unit["unit"] == "money"
    saved = get_facts(ctx.conn, ctx.store_id, [margin["fact_id"]], with_lineage=True)
    roles = [p.role for p in saved[margin["fact_id"]].lineage.parents]
    assert roles == [f"operand:F{i}" for i in sorted((r, c))]  # operands, by fact id
    bad = {
        f"F{r} * 1.1": "invalid_expression",  # no literal numbers
        f"F{r} + F{u}": "invalid_expression",  # money + count
        f"F{r} * F{c}": "invalid_expression",  # money x money
        f"F{r} ** F{c}": "invalid_expression",
        f"F{r} +": "invalid_expression",
        f"F{r} + x": "invalid_expression",
        f"F{r} + F{c} + F{u}": "invalid_expression",  # F{u} not listed in fact_ids below
    }
    for expression, code in bad.items():
        assert error(ctx, "compute", {"expression": expression, "fact_ids": [r, c]}) == code
    assert error(ctx, "compute", {"expression": "F999999", "fact_ids": [999999]}) == (
        "unknown_fact"
    )


def test_compute_division_by_zero_gives_an_undefined_fact(ctx: ToolContext) -> None:
    far = {"start": "2020-01-01", "end": "2020-01-08"}  # no sales at all
    store_scope = {"kind": "store", "id": None}
    revenue = call(ctx, "get_facts", metric="revenue", scope=store_scope, period=far)["fact"]
    units = call(ctx, "get_facts", metric="units", scope=store_scope, period=far)["fact"]
    out = call(
        ctx,
        "compute",
        expression=f"F{revenue['fact_id']} / F{units['fact_id']}",
        fact_ids=[revenue["fact_id"], units["fact_id"]],
    )["fact"]
    assert (out["status"], out["value"]) == ("undefined", None)
    assert out["undefined_reason"] == "the divisor is zero"


def test_unknown_tools_and_bad_arguments_are_refused(ctx: ToolContext) -> None:
    registry = build_registry()
    outcome, _ = registry.execute(ctx, ToolCall("c9", "pause_campaign", '{"campaign_id": "x"}'))
    assert (outcome.ok, outcome.error_code) == (False, "unknown_tool")
    assert "read-only" in (outcome.error or "")
    assert [c.name for c in registry.refused] == ["pause_campaign"]
    assert error(ctx, "get_facts", "{not json") == "invalid_arguments"
    assert error(ctx, "get_incident", {"incident_id": "inc-0", "extra": 1}) == "invalid_arguments"


# --- read-only guarantees -------------------------------------------------------------------

FORBIDDEN_IMPORTS = {
    "app.domain.repositories",
    "app.settings.repository",
    "app.domain.audit",
}
FORBIDDEN_NAMES = {
    "insert",
    "update",
    "delete",
    "append_audit",
    "IncidentRepository",
    "StoreSettingsRepository",
}


def test_no_tool_module_is_bound_to_a_write_repository() -> None:
    for path in TOOLS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in FORBIDDEN_IMPORTS, (path.name, node.module)
                names = {a.name for a in node.names}
                assert not names & FORBIDDEN_NAMES, (path.name, names & FORBIDDEN_NAMES)
                assert not any(n.endswith("Repository") for n in names), (path.name, names)
            if isinstance(node, ast.Import):
                assert not {a.name for a in node.names} & FORBIDDEN_IMPORTS
    for tool in TOOLS:
        assert tool.run.__module__.startswith("app.agent.tools."), tool.name


class _Nothing(ToolInput):
    pass


class _Done(ToolResult):
    pass


def _sneaky_write(ctx: ToolContext, _: _Nothing) -> _Done:
    ctx.conn.execute(
        text("UPDATE products SET name = 'pwned' WHERE store_id = :s"), {"s": ctx.store_id}
    )
    return _Done()


def test_the_write_guard_refuses_business_writes(ctx: ToolContext) -> None:
    rogue = type(build_registry())([Tool("rogue", "x", _Nothing, _Done, _sneaky_write)])
    with pytest.raises(WriteForbiddenError, match="update on 'products'"):
        rogue.execute(ctx, ToolCall("c1", "rogue", "{}"))
    with facts_only(ctx.conn), pytest.raises(WriteForbiddenError, match="insert"):
        _insert_product(ctx.conn, ctx.store_id)
    with facts_only(ctx.conn):
        ctx.conn.execute(text("SELECT 1"))  # reads pass
    _insert_product(ctx.conn, ctx.store_id)  # outside a tool the guard is off


def _insert_product(conn: Connection, store_id: UUID) -> None:
    conn.execute(
        insert(products).values(
            id=uuid4(),
            store_id=store_id,
            sku="x",
            name="x",
            price=1,
            unit_cost=1,
            unit_fee=0,
            currency="USD",
        )
    )


def test_period_input_limits() -> None:
    with pytest.raises(ValueError, match="366"):
        PeriodInput(start="2025-01-01", end="2026-06-01")  # type: ignore[arg-type]


def test_identical_calls_are_memoised(ctx: ToolContext) -> None:
    registry = build_registry()
    first, _ = registry.execute(ctx, ToolCall("c1", "get_data_quality", "{}"))
    again, output = registry.execute(ctx, ToolCall("c2", "get_data_quality", " { } "))
    assert again is first  # same validated arguments: no second run
    assert output.call_id == "c2"
    assert (registry.calls, registry.memo_hits) == (2, 1)
    fresh = build_registry()  # a new investigation starts with an empty memo
    fresh.execute(ctx, ToolCall("c3", "get_data_quality", "{}"))
    assert fresh.memo_hits == 0


def test_large_results_are_truncated_with_a_marker(ctx: ToolContext, store: dict[str, Any]) -> None:
    tight = build_registry(max_result_chars=3000)
    outcome, output = tight.execute(
        ctx, ToolCall("c1", "get_incident", json.dumps({"incident_id": store["incident"]}))
    )
    assert outcome.ok
    assert outcome.truncated
    assert len(json.dumps(outcome.result)) <= 3000
    assert json.loads(output.output)["truncated"] is True


def test_list_incidents(ctx: ToolContext, store: dict[str, Any]) -> None:
    alerts = call(ctx, "list_incidents", include_watchlist=False)["incidents"]
    everything = call(ctx, "list_incidents", include_watchlist=True)["incidents"]
    assert alerts[0]["incident_id"] == store["incident"]
    assert alerts[0]["top_cause"] == "stockout_on_promoted"
    assert {i["alert"] for i in alerts} <= {"critical", "high", "normal", "data_quality"}
    assert len(everything) >= len(alerts)
    assert numbers_outside_facts(everything) == []


def test_list_products(ctx: ToolContext, store: dict[str, Any]) -> None:
    view = call(ctx, "list_products", sort="contribution_margin")
    products = [p for p in view["products"] if p != TRUNCATED]  # long lists are cut
    assert products
    margins = [p["contribution_margin_last_28_days"]["value"] for p in products]
    defined = [Decimal(m) for m in margins if m is not None]
    assert defined == sorted(defined, reverse=True)
    assert all(p["product"]["name"].startswith(f"{OPEN}data kind=product_name") for p in products)
    assert numbers_outside_facts(view) == []
    newest = [p for p in call(ctx, "list_products", sort="newest")["products"] if p != TRUNCATED]
    firsts = [p["first_sale"] for p in newest if p["first_sale"]]
    assert firsts == sorted(firsts, reverse=True)
