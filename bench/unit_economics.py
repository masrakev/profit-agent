"""Unit economics from measured costs (Task 5 B6).

    uv run python -m bench.unit_economics      # writes bench/reports/unit-economics.md and the
                                               # section 7 table of docs/launch-readiness.md

Inputs, all measured: the golden question runs with production routing (each answer's cost,
and the investigations behind diagnoses), the briefing costs on the golden scenarios
(bench/reports/briefing-costs.md), and the spend ledger as a cross-check of each run's total.
Costs are at Standard prices: on synthetic stores classification runs on the Contributor model,
a real store pays the Standard price for every call.

Per store and month: the profile's investigations and questions, 26 daily briefs, 4 weekly
reports and 1 monthly review, email, payment processing and a share of the infrastructure.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT, get_settings, repo_path
from bench.runner.report import REPORT_DIR

READINESS = REPO_ROOT / "docs" / "launch-readiness.md"
BEGIN, END = "<!-- unit-economics:begin -->", "<!-- unit-economics:end -->"
BRIEFINGS_PER_MONTH = {"daily": 26, "weekly": 4, "monthly": 1}
EMAIL_USD = Decimal("0.05")
PAYMENT_RATE, PAYMENT_FIXED = Decimal("0.03"), Decimal("0.30")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Profile:
    name: str
    investigations: int
    questions: int
    infra: Decimal
    price: Decimal
    worst: bool = False  # every investigation at the most expensive one measured


PROFILES = (
    Profile("Typical store", 10, 30, Decimal("2.00"), Decimal("49")),
    Profile("Busy store", 40, 150, Decimal("4.00"), Decimal("149")),
    Profile(
        "Busy, every investigation at max cost", 40, 150, Decimal("4.00"), Decimal("149"), True
    ),
)


@dataclass(frozen=True)
class Measured:
    investigation_mean: Decimal
    investigation_max: Decimal
    investigations: int
    answer_mean: Decimal
    answer_max: Decimal
    answers: int
    briefing_mean: dict[str, Decimal]
    briefings: dict[str, int]
    runs: list[dict[str, Any]]


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def ledger_totals(path: Path) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    if not path.exists():
        return totals
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        run = entry.get("run_id") or ""
        totals[run] = totals.get(run, Decimal(0)) + _d(entry["amount"])
    return totals


def measure(reports: Path, ledger: dict[str, Decimal]) -> Measured:
    runs, answers, means, maxima, counts = [], [], [], [], []
    for path in sorted(reports.glob("golden-*-production.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        inv = data["summary"]["investigations"]
        costs = [
            _d(q["usage"]["standard_cost_usd"])
            for q in data["questions"]
            if not q.get("pending") and q.get("usage")
        ]
        answers.extend(costs)
        counts.append(int(inv["n"]))
        means.append(_d(inv["standard_cost_usd_mean"]) * int(inv["n"]))
        maxima.append(_d(inv["cost_usd_max"]))
        run_id = "golden-" + re.sub(r"[-:]|\+00:00", "", data["meta"]["started"]) + "Z"
        reported = _d(data["summary"]["cost_usd"]) + _d(inv["cost_usd"])
        runs.append(
            {
                "run": run_id,
                "answers": len(costs),
                "investigations": int(inv["n"]),
                "reported_usd": reported,
                "ledger_usd": ledger.get(run_id),
            }
        )
    briefings = sorted(reports.glob("briefing-costs-*.json"))[-1]
    rows = json.loads(briefings.read_text(encoding="utf-8"))["rows"]
    by_kind: dict[str, list[Decimal]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(_d(row["cost_usd"]))
    return Measured(
        investigation_mean=sum(means, Decimal(0)) / sum(counts),
        investigation_max=max(maxima),
        investigations=sum(counts),
        answer_mean=sum(answers, Decimal(0)) / len(answers),
        answer_max=max(answers),
        answers=len(answers),
        briefing_mean={k: sum(v, Decimal(0)) / len(v) for k, v in by_kind.items()},
        briefings={k: len(v) for k, v in by_kind.items()},
        runs=runs,
    )


def _money(x: Decimal) -> str:
    return f"USD {x.quantize(CENT, rounding=ROUND_HALF_EVEN)}"


def _unit(x: Decimal) -> str:
    """A unit cost: four decimals (a briefing costs less than a cent)."""
    return f"USD {x.quantize(Decimal('0.0001'), rounding=ROUND_HALF_EVEN)}"


def profile_row(p: Profile, m: Measured) -> dict[str, Decimal]:
    investigation = m.investigation_max if p.worst else m.investigation_mean
    briefings = sum((m.briefing_mean[k] * n for k, n in BRIEFINGS_PER_MONTH.items()), Decimal(0))
    model = investigation * p.investigations + m.answer_mean * p.questions + briefings
    payment = p.price * PAYMENT_RATE + PAYMENT_FIXED
    total = model + p.infra + EMAIL_USD + payment
    return {
        "model": model,
        "briefings": briefings,
        "payment": payment,
        "total": total,
        "margin": (p.price - total) / p.price,
    }


def profiles_table(m: Measured) -> list[str]:
    lines = [
        "| Profile | Investigations | Questions | Model cost | Infra | Email | Payment | "
        "Total cost | Price | Gross margin |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in PROFILES:
        r = profile_row(p, m)
        lines.append(
            f"| {p.name} | {p.investigations} | {p.questions} | {_money(r['model'])} | "
            f"{_money(p.infra)} | {_money(EMAIL_USD)} | {_money(r['payment'])} | "
            f"{_money(r['total'])} | {_money(p.price)} / month | {r['margin']:.0%} |"
        )
    return lines


def readiness_block(m: Measured) -> str:
    b = m.briefing_mean
    lines = [
        BEGIN,
        "Generated by `uv run python -m bench.unit_economics` from measured costs at Standard "
        "prices (`bench/reports/unit-economics.md`): an investigation "
        f"{_unit(m.investigation_mean)} on average ({_unit(m.investigation_max)} at most, "
        f"{m.investigations} investigations), an Ask answer {_unit(m.answer_mean)} "
        f"({m.answers} answers), a daily brief {_unit(b['daily'])}, a weekly report "
        f"{_unit(b['weekly'])}, a monthly review {_unit(b['monthly'])}.",
        "",
        "Per store and month: 26 daily briefs, 4 weekly reports, 1 monthly review, email "
        f"{_money(EMAIL_USD)}, payment processing 3% + USD 0.30; infrastructure is an estimate "
        "for a shared deployment.",
        "",
        *profiles_table(m),
        END,
    ]
    return "\n".join(lines)


def report(m: Measured) -> str:
    def cost(x: Decimal) -> str:
        return f"{x.quantize(Decimal('0.0001'), rounding=ROUND_HALF_EVEN)}"

    lines = [
        "# Unit economics",
        "",
        "Generated by `uv run python -m bench.unit_economics` from measured costs at Standard "
        "prices: the golden question runs with production routing, the briefing costs on the "
        "golden scenarios, and the spend ledger as a check of each run's total.",
        "",
        "| Item | Measured | Mean USD | Max USD |",
        "| --- | --- | --- | --- |",
        f"| Investigation (Spark, Wonder on escalation) | {m.investigations} | "
        f"{cost(m.investigation_mean)} | {cost(m.investigation_max)} |",
        f"| Ask answer (classification and answer) | {m.answers} | {cost(m.answer_mean)} | "
        f"{cost(m.answer_max)} |",
    ]
    for kind in ("daily", "weekly", "monthly"):
        lines.append(
            f"| Briefing, {kind} | {m.briefings[kind]} | {cost(m.briefing_mean[kind])} | - |"
        )
    briefings = profile_row(PROFILES[0], m)["briefings"]
    lines += [
        "",
        "## Per store and month",
        "",
        *profiles_table(m),
        "",
        f"Briefings are {_money(briefings)} of each profile's model cost (26 daily, 4 weekly, "
        "1 monthly). Total cost includes payment processing.",
    ]
    lines += [
        "",
        "## Check against the spend ledger",
        "",
        "| Run | Answers | Investigations | Reported USD | Ledger USD |",
        "| --- | --- | --- | --- | --- |",
    ]
    for run in m.runs:
        ledger = run["ledger_usd"]
        lines.append(
            f"| `{run['run']}` | {run['answers']} | {run['investigations']} | "
            f"{cost(run['reported_usd'])} | {cost(ledger) if ledger is not None else 'n/a'} |"
        )
    lines += [
        "",
        "The ledger records every call, failed ones included; the reports count the answers and "
        "investigations they kept. Prices are working hypotheses for design partners to test.",
    ]
    return "\n".join(lines) + "\n"


def update_readiness(path: Path, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    start, end = text.index(BEGIN), text.index(END) + len(END)
    path.write_text(text[:start] + block + text[end:], encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unit economics from measured costs")
    parser.add_argument("--reports", type=Path, default=REPORT_DIR)
    parser.add_argument("--no-doc", action="store_true", help="do not update the readiness doc")
    args = parser.parse_args(argv)
    m = measure(args.reports, ledger_totals(repo_path(get_settings().llm_spend_ledger)))
    text = report(m)
    (args.reports / "unit-economics.md").write_text(text, encoding="utf-8", newline="\n")
    if not args.no_doc:
        update_readiness(READINESS, readiness_block(m))
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
