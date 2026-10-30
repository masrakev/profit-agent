"""Citation completeness: an answer that names a metric cites a fact of that metric.

The vocabulary is the fact registry's metrics, by their names ("contribution margin",
"net profit", "ad spend") plus a few established synonyms ("ROAS", "cost per purchase",
"stock cover"). Longer names win over the names they contain ("refund rate" is not "refunds",
"promoted revenue" is not "revenue"). A cited fact covers a metric when its formula is the
metric, or one of its parts or variants: `profit_driver.refunds`, `twin.change.units`,
`expected_monthly_impact` covers nothing but itself.
"""

import re
from collections.abc import Callable, Iterable
from functools import cache

from app.agent.contracts import Answer
from app.agent.guard import OutputViolation
from app.facts.formulas import REGISTRY

SYNONYMS: dict[str, tuple[str, ...]] = {
    "ad_spend": ("ad spend", "ads spend", "advertising spend"),
    "cpa": ("cpa", "cost per purchase", "cost per acquisition"),
    "poas": ("poas", "profit on ad spend"),
    "roas": ("roas", "return on ad spend"),
    "mer": ("mer", "marketing efficiency ratio"),
    "cogs": ("cogs", "cost of goods sold"),
    "inventory_cover_days": ("inventory cover", "stock cover", "days of cover"),
    "units_on_hand": ("units on hand", "stock on hand"),
    "supplier_lead_time_days": ("supplier lead time",),
    "contribution_after_ads": ("contribution after ads", "contribution after ad spend"),
}


def _names(metric: str) -> tuple[str, ...]:
    base = metric.replace("_", " ")
    return tuple(dict.fromkeys((base, *SYNONYMS.get(metric, ()))))


SINGULAR = frozenset({"refunds", "fees"})  # "a refund", "the fee"; not "unit cost", "in order"


def _pattern(name: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in name.split()]
    if name in SINGULAR:
        words[-1] = words[-1][:-1] + "s?"
    return re.compile(r"(?i)(?<![\w{])" + r"\s+".join(words) + r"(?![\w}])")


@cache
def vocabulary() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """(metric, pattern) pairs, longest names first."""
    pairs = [(f.formula_id, name) for f in REGISTRY for name in _names(f.formula_id)]
    pairs.sort(key=lambda p: -len(p[1]))
    return tuple((metric, _pattern(name)) for metric, name in pairs)


def named_metrics(texts: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for text in texts:
        masked = text
        for metric, pattern in vocabulary():
            if pattern.search(masked):
                found.add(metric)
                masked = pattern.sub(lambda m: " " * len(m.group(0)), masked)
    return found


def covers(formula_id: str, metric: str) -> bool:
    return (
        formula_id == metric
        or formula_id.startswith(f"{metric}.")
        or formula_id.endswith(f".{metric}")
        or f".{metric}." in formula_id
    )


def answer_texts(answer: Answer) -> list[str]:
    return [
        answer.answer,
        answer.reasoning or "",
        answer.uncertainty,
        answer.recommendation or "",
        answer.would_change_my_mind or "",
        *answer.alternatives,
    ]


FormulaLookup = Callable[[list[int]], dict[int, str]]


def citation_check(formulas: FormulaLookup) -> Callable[[Answer], list[OutputViolation]]:
    """Reject an answer naming a metric that none of its cited facts is about."""

    def check(answer: Answer) -> list[OutputViolation]:
        named = named_metrics(answer_texts(answer))
        if not named:
            return []
        cited = set(formulas(sorted(set(answer.evidence))).values())
        missing = sorted(m for m in named if not any(covers(f, m) for f in cited))
        if not missing:
            return []
        return [
            OutputViolation(
                "evidence",
                "contract",
                "you name metrics without citing a fact of them: "
                + ", ".join(m.replace("_", " ") for m in missing)
                + "; cite one for each, or do not name it",
            )
        ]

    return check
