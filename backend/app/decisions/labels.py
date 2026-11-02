"""Readable labels for decisions and their options, naming the campaign or product they act on:
"Pause ‘Trail Jacket — Prospecting’ until restock", "Cut the daily budget of ‘Spring Sale’ by 30%".

Written by code from the options' kinds and actions, and the entities' names read from the
database (merchant data: a client shows them as text). Percentages and amounts come from the
backend formatter, like every number the owner reads.
"""

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from app.decisions.options import OptionKind
from app.facts.model import Unit
from app.twin import ActionKind
from app.verifier.render import display_value, format_share

DO_NOTHING = "Do nothing"
PRODUCT_ACTIONS = {ActionKind.CHANGE_PRICE.value, ActionKind.LAUNCH_CAMPAIGN.value}

# Options that act on nothing yet (the owner carries them out), by kind; `{e}` is the entity.
PREPARED: dict[str, str] = {
    OptionKind.PREPARE_REORDER: "Prepare a reorder of {e}",
    OptionKind.PREPARE_PRICE_CHANGE: "Prepare a price change for {e}",
    OptionKind.REVIEW_SUPPLIER: "Review the supplier of {e}",
    OptionKind.INCREMENTALITY_TEST: "Run an incrementality test on {e}",
    OptionKind.INVESTIGATE_PRODUCT_QUALITY: "Look into the quality of {e}",
    OptionKind.FIX_TRACKING: "Fix the tracking of {e}",
    OptionKind.MONITOR: "Keep watching {e}",
    OptionKind.PAUSE_CAMPAIGN: "Pause {e}",
    OptionKind.PAUSE_UNTIL_RESTOCK: "Pause the ads of {e} until restock",
    OptionKind.REDUCE_BUDGET: "Reduce the daily budget of {e}",
    OptionKind.INCREASE_BUDGET: "Raise the daily budget of {e}",
}


def entity_refs(entity: str, actions: Iterable[Mapping[str, Any]]) -> set[str]:
    """The references whose names a label needs: the option's entity and its actions'."""
    refs = {entity} if entity != "store" else set()
    for action in actions:
        target = action.get("entity")
        if target:
            kind = "product" if action.get("kind") in PRODUCT_ACTIONS else "campaign"
            refs.add(f"{kind}:{target}")
    return refs


def _name(ref: str, names: Mapping[str, str]) -> str:
    """A campaign's name in quotes, a product's as it is, the store as "the store"."""
    if ref == "store" or ref.endswith(":*"):
        return "the store" if ref == "store" else "every campaign"
    kind, _, _ = ref.partition(":")
    name = names.get(ref)
    if name is None:
        return f"a {kind}"  # an entity deleted since: still a readable label
    return f"‘{name}’" if kind == "campaign" else name


def _action(action: Mapping[str, Any], kind: str, names: Mapping[str, str], currency: str) -> str:
    act = action.get("kind")
    target = action.get("entity")
    change = Decimal(str(action.get("change") or 0))
    if act == ActionKind.PAUSE_CAMPAIGN.value:
        phrase = f"pause {_name(f'campaign:{target}', names)}"
        return phrase + (" until restock" if kind == OptionKind.PAUSE_UNTIL_RESTOCK else "")
    if act == ActionKind.CHANGE_BUDGET.value:
        budget = action.get("daily_budget")
        campaign = _name(f"campaign:{target}", names)
        if budget is not None:
            amount = display_value(Decimal(str(budget)), Unit.MONEY, currency)
            return f"set the daily budget of {campaign} to {amount}"
        verb = "cut" if change < 0 else "raise"
        return f"{verb} the daily budget of {campaign} by {format_share(change)}"
    if act == ActionKind.CHANGE_ALL_AD_SPEND.value:
        verb = "cut" if change < 0 else "raise"
        return f"{verb} every campaign's daily budget by {format_share(change)}"
    if act == ActionKind.CHANGE_PRICE.value:
        verb = "lower" if change < 0 else "raise"
        return f"{verb} the price of {_name(f'product:{target}', names)} by {format_share(change)}"
    if act == ActionKind.LAUNCH_CAMPAIGN.value:
        return f"launch a campaign for {_name(f'product:{target}', names)}"
    if act == ActionKind.RESTOCK_PRODUCT.value:
        return f"restock {_name(f'product:{target}', names)}"
    return str(act).replace("_", " ")


def option_label(
    kind: str,
    entity: str,
    actions: Iterable[Mapping[str, Any]],
    names: Mapping[str, str],
    currency: str,
) -> str:
    """What the option does, naming what it acts on."""
    phrases = [_action(a, kind, names, currency) for a in actions]
    if phrases:
        text = " and ".join(phrases)
        return text[0].upper() + text[1:]
    template = PREPARED.get(kind)
    if template is None:
        words = kind.replace("_", " ")
        return f"{words[0].upper()}{words[1:]} ({_name(entity, names)})"
    return template.format(e=_name(entity, names))


def decision_label(recommended_label: str) -> str:
    """The question the decision asks: its recommended option."""
    return f"{recommended_label}?"
