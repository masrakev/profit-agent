"""Options on the golden scenarios, for review (ADR 0015).

    uv run python -m bench.twin.options_report      # writes bench/reports/options-golden.md

Each golden scenario with a labelled cause is loaded, the twin is fitted at its data end, and
the options of the labelled cause (an underfunded campaign for the matching condition) are
built, simulated and ranked by the rule of app.decisions.options. Store-wide causes (fee
increase, mix shift) have no catalogue entry and get "monitor".
"""

import sys
from datetime import UTC, datetime
from decimal import Decimal

from app.db import make_engine, tenant_transaction
from app.decisions.options import UNDERFUNDED_CAMPAIGN, OptionSet, build_options
from app.observability import configure_logging
from app.twin import fit_twin
from bench.generator.load import load
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.scenarios.manifest import ScenarioManifest, load_suite

PRODUCT_CAUSES = frozenset({"stockout_on_promoted", "supplier_cost_increase", "refund_spike"})


def cause_of(manifest: ScenarioManifest) -> tuple[str, str] | None:
    if manifest.labels:
        label = manifest.labels[0]
        cause = label.fault_type.value
        kind = "product" if cause in PRODUCT_CAUSES else "campaign"
        entity = next((e for e in label.entities if e.kind.value == kind), None)
        return (cause, f"{kind}:{entity.id}") if entity is not None else (cause, "store")
    for condition in manifest.condition_labels:
        if "underfunded" in condition.kind.value:
            campaign = next(e for e in condition.entities if e.kind.value == "campaign")
            return UNDERFUNDED_CAMPAIGN, f"campaign:{campaign.id}"
    return None


def _money(x: float) -> str:
    return f"{x:,.0f}"


def section(scenario: str, built: OptionSet) -> list[str]:
    lines = [
        f"### `{scenario}`: {built.cause} on `{built.entity}`",
        "",
        f"Floor over {built.horizon_days} days: {built.floor}. Recommended: "
        f"`{built.option(built.recommended).kind.value}` ({built.reason}).",
        "",
        "| Option | Family | Net-profit change P10 / P50 / P90 | Reversibility | Weak evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for o in built.options:
        r = o.impact
        change = "not simulated" if r is None else " / ".join(map(_money, r))
        size = ""
        if o.actions and o.actions[0].change:
            size = f" {float(o.actions[0].change):+.0%}"
        if o.actions and o.actions[0].days:
            size += f" for {o.actions[0].days} days"
        weak = "; ".join(o.simulation.low_evidence) if o.simulation else ""
        mark = " (recommended)" if o.option_id == built.recommended else ""
        lines.append(
            f"| {o.kind.value}{size}{mark} | {o.action_family.value} | {change} | "
            f"{o.reversibility.value} | {weak} |"
        )
    return [*lines, ""]


def main() -> int:
    configure_logging("WARNING")
    engine = make_engine(prepare_database("profit_options"))
    started = datetime.now(UTC).replace(microsecond=0)
    lines = [
        "# Options on the golden scenarios",
        "",
        f"Run {started.isoformat()}. Twin fitted at each store's data end; ranges are the "
        "simulated change in net profit against doing nothing over 14 days (calibrated, store "
        "currency).",
        "",
    ]
    for manifest in load_suite("golden"):
        found = cause_of(manifest)
        if found is None:
            continue
        data = manifest.generate()
        load(engine, data, manifest.config)
        with tenant_transaction(engine, data.store.store_id) as conn:
            model = fit_twin(conn, data.store.store_id)
        built = build_options(model, found[0], found[1], floor_monthly=Decimal(100))
        lines += section(manifest.scenario_id, built)
    text = "\n".join(lines)
    (REPORT_DIR / "options-golden.md").write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
