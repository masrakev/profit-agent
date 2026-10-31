"""The plan validation's own logic (bench/goals_plans.py), on hand-built plans and rows."""

import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.goals.levers import DECISION, MANUAL, Step
from app.twin import Action, ActionKind
from bench import goals_plans as gp
from bench.generator import Intervention

A, B, P = UUID(int=1), UUID(int=2), UUID(int=3)


def step(*actions: Action, day: int = 0, kind: str = DECISION) -> Step:
    return Step(
        lever="scale_profitable", kind=kind, day=day, actions=actions, summary="", evidence=()
    )


def test_steps_become_interventions_from_their_day() -> None:
    plan: Any = SimpleNamespace(
        steps=(
            (step(Action(kind=ActionKind.CHANGE_BUDGET, entity=B, change=Decimal("0.2"))), ()),
            (step(Action(kind=ActionKind.PAUSE_CAMPAIGN, entity=A, days=7), day=3), ()),
            (step(Action(kind=ActionKind.RESTOCK_PRODUCT, entity=P, start=5), kind=MANUAL), ()),
        )
    )
    plain: Any = SimpleNamespace(campaigns=[SimpleNamespace(id=A), SimpleNamespace(id=B)])
    interventions, executed, skipped = gp.follow(plan, plain, cut=100)
    assert interventions == [
        Intervention(day=100, campaign=1, budget_multiplier=1.2),
        Intervention(day=103, campaign=0, budget_multiplier=0.0),
        Intervention(day=110, campaign=0, budget_multiplier=1.0),  # back after its days
    ]
    assert (executed, skipped) == (3, 1)  # the reorder is not executed


def row(scenario: str, metric: str, *, without: bool, with_plan: bool, **kw: Any) -> gp.Row:
    base = gp.Row(
        scenario=scenario,
        cut=250,
        metric=metric,
        target=100.0,
        steps=["scale_profitable"],
        executed=1,
        skipped=0,
        p_without=0.3,
        p_with=0.5,
        reached_without=without,
        reached_with=with_plan,
        outcome=(90.0, 100.0, 110.0),
        actual_with=105.0,
        actual_without=95.0,
        profit_change=(-5.0, 10.0, 25.0),
        actual_profit_change=12.0,
        milestones=[(7, 10.0, 20.0, 15.0), (14, 20.0, 40.0, 50.0)],
    )
    return replace(base, **kw)


def test_summary_uplift_bands_and_report(tmp_path: Path) -> None:
    rows = [
        row("s1", "net_profit", without=False, with_plan=True),
        row("s1", "revenue", without=True, with_plan=True),
        row("s2", "net_profit", without=False, with_plan=False, steps=[], actual_with=200.0),
        row("s2", "revenue", without=False, with_plan=True),
    ]
    s = gp.summary(rows)
    a = s["all"]
    assert (a["goals"], a["with_steps"]) == (4, 3)
    assert (a["reached_without"], a["reached_with"]) == (0.25, 0.75)
    uplift, low, high = a["uplift"]
    assert uplift == 0.5
    assert low <= uplift <= high
    assert a["milestone_hits"] == 0.5  # one week inside its band, one above, per plan with steps
    assert a["outcome_coverage"] == 0.75
    assert a["profit_change_predicted"] == 10.0
    assert a["profit_change_realised"][0] == 12.0
    assert set(s) == {"all", "net_profit", "revenue"}
    text = gp.report("goals_dev", "run", rows, s)
    assert "| all | 4 | 3 | 25% (30%) | 75% (50%) | +50.0 points" in text
    assert "Milestone bands: 50% of weeks inside" in text
    assert "missed" in text
    assert "| `scale_profitable` | 3 |" in text
    saved = tmp_path / "plans.jsonl"
    assert gp._load_saved(saved) == []
    saved.write_text("".join(json.dumps(asdict(r)) + "\n" for r in rows), encoding="utf-8")
    assert [r.scenario for r in gp._load_saved(saved)] == ["s1", "s1", "s2", "s2"]
