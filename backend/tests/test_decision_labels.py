"""Decisions and options read as labels naming what they act on, worded by code."""

from decimal import Decimal
from typing import Any

import pytest

from app.decisions.labels import DO_NOTHING, decision_label, entity_refs, option_label
from app.verifier.render import format_share

CAMPAIGN = "6433a313-4edd-55d2-a5f8-baf1fc04ed95"
OTHER = "ef059977-c250-5493-9b6f-2a67cd56629b"
PRODUCT = "ea63836b-e0d7-5298-b9db-b58631ed27f1"
NAMES = {
    f"campaign:{CAMPAIGN}": "Trail Jacket — Prospecting",
    f"campaign:{OTHER}": "Trail Essentials — Retargeting",
    f"product:{PRODUCT}": "Trail Jacket",
}


def act(kind: str, entity: str | None = CAMPAIGN, **fields: Any) -> dict[str, Any]:
    return {"kind": kind, "entity": entity, "change": "0", "days": None, **fields}


@pytest.mark.parametrize(
    ("kind", "entity", "actions", "label"),
    [
        (
            "pause_until_restock",
            f"product:{PRODUCT}",
            [act("pause_campaign", days=14)],
            "Pause ‘Trail Jacket — Prospecting’ until restock",
        ),
        (
            "reduce_budget",
            f"campaign:{CAMPAIGN}",
            [act("change_budget", change="-0.30")],
            "Cut the daily budget of ‘Trail Jacket — Prospecting’ by 30%",
        ),
        (
            "increase_budget",
            f"campaign:{OTHER}",
            [act("change_budget", OTHER, change="0.125")],
            "Raise the daily budget of ‘Trail Essentials — Retargeting’ by 12.5%",
        ),
        (
            "reduce_budget",
            f"campaign:{CAMPAIGN}",
            [act("change_budget", change="-0.3"), act("change_budget", OTHER, change="0.3")],
            "Cut the daily budget of ‘Trail Jacket — Prospecting’ by 30% and raise the daily "
            "budget of ‘Trail Essentials — Retargeting’ by 30%",
        ),
        (
            "increase_budget",
            f"campaign:{CAMPAIGN}",
            [act("change_budget", daily_budget="80.6")],
            "Set the daily budget of ‘Trail Jacket — Prospecting’ to $81",
        ),
        (
            "prepare_price_change",
            f"product:{PRODUCT}",
            [act("change_price", PRODUCT, change="-0.1")],
            "Lower the price of Trail Jacket by 10%",
        ),
        (
            "launch",
            f"product:{PRODUCT}",
            [act("launch_campaign", PRODUCT)],
            "Launch a campaign for Trail Jacket",
        ),
        (
            "restock",
            f"product:{PRODUCT}",
            [act("restock_product", PRODUCT)],
            "Restock Trail Jacket",
        ),
        (
            "cut_all",
            "store",
            [act("change_all_ad_spend", None, change="-0.2")],
            "Cut every campaign's daily budget by 20%",
        ),
        ("prepare_reorder", f"product:{PRODUCT}", [], "Prepare a reorder of Trail Jacket"),
        ("monitor", "store", [], "Keep watching the store"),
        ("fix_tracking", "campaign:*", [], "Fix the tracking of every campaign"),
        ("something_new", f"product:{PRODUCT}", [], "Something new (Trail Jacket)"),
    ],
)
def test_options_name_what_they_act_on(
    kind: str, entity: str, actions: list[dict[str, Any]], label: str
) -> None:
    assert option_label(kind, entity, actions, NAMES, "USD") == label


def test_a_deleted_entity_still_reads() -> None:
    gone = "00000000-0000-0000-0000-000000000001"
    assert option_label(
        "pause_campaign", f"campaign:{gone}", [act("pause_campaign", gone)], {}, "USD"
    ) == ("Pause a campaign")


def test_labels_need_the_names_of_entities_and_targets() -> None:
    actions = [act("change_budget"), act("change_price", PRODUCT)]
    assert entity_refs(f"campaign:{OTHER}", actions) == {
        f"campaign:{OTHER}",
        f"campaign:{CAMPAIGN}",
        f"product:{PRODUCT}",
    }
    assert entity_refs("store", []) == set()


def test_a_decision_asks_its_recommended_option() -> None:
    assert decision_label("Pause ‘Trail Jacket — Prospecting’ until restock") == (
        "Pause ‘Trail Jacket — Prospecting’ until restock?"
    )
    assert DO_NOTHING == "Do nothing"


def test_shares_are_percentages() -> None:
    assert format_share(Decimal("-0.3")) == "30%"
    assert format_share(Decimal("0.125")) == "12.5%"
    assert format_share(Decimal("0.3333")) == "33.3%"
    assert format_share(Decimal("1")) == "100%"
