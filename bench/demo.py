"""The demo loop on the seeded demo store (Task 4, SPEC section 0; Task 5 B7).

    uv run python -m bench.demo        # make demo: seeds the store afresh, writes
                                       # bench/reports/demo-stockout.md

1. The demo store is seeded as `make demo-seed` does (bench/demo_seed.py): 14 days before its
   data end, the critical stockout alert (ads still spending on a product that is out of
   stock) with its investigation, and its decision pending: the options for the cause,
   simulated by the twin; the recommended one pauses the campaigns that promote the product
   until it is restocked.
2. The owner approves it through the signed, single-use email link (the API's email channel):
   opening the link shows the decision; confirming it decides.
3. The worker runs the policy engine and executes the pause: on the Meta sandbox campaign linked
   to the store's campaign (META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_CAMPAIGN_LINKS), mirrored
   on the simulator so the outcome can be measured. Without sandbox credentials the Meta side
   runs against the documented-contract fake (bench/meta_fake.py), and the report says so.
4. Seven days pass (the pause's observation window); the supplier restocks.
5. The owner rolls the pause back through the API: the campaign resumes, the stock is back.
6. Seven more days pass; the pause's outcome is measured by synthetic control, next to the
   twin's prediction made when the decision was proposed.
7. The journal, from the API, shows the loop in order, after the store's past decisions.
"""

import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.api.deps import get_app_settings, get_engine
from app.api.main import app
from app.causal.outcome import measure
from app.config import Settings, get_settings
from app.db import make_engine, tenant_transaction
from app.decisions.store import get
from app.executor.adapters import Adapter
from app.executor.meta import MetaAdsAdapter
from app.executor.simulator import SimulatorAdapter
from app.executor.worker import Executor
from app.observability import configure_logging
from bench.demo_seed import DEMO_DB, SCENARIO, Seeded, demo_provider, seed
from bench.meta_fake import ACCOUNT, FakeCampaign, FakeGraph
from bench.runner.__main__ import prepare_database
from bench.runner.report import REPORT_DIR
from bench.simulator import advance

FAKE_CAMPAIGN = "120200000000001"


def _meta(
    settings: Settings, campaign: UUID, budget: Decimal
) -> tuple[Adapter, dict[str, str], str, FakeGraph | None]:
    if (
        settings.meta_access_token
        and settings.meta_ad_account_id
        and str(campaign) in (settings.meta_campaign_links)
    ):
        adapter = MetaAdsAdapter(
            access_token=settings.meta_access_token.get_secret_value(),
            ad_account_id=settings.meta_ad_account_id,
        )
        return adapter, dict(settings.meta_campaign_links), "Meta sandbox (live)", None
    graph = FakeGraph(campaigns={FAKE_CAMPAIGN: FakeCampaign(daily_budget=int(budget * 100))})
    adapter = MetaAdsAdapter(
        access_token="fake-token",  # noqa: S106
        ad_account_id=ACCOUNT,
        transport=graph.transport(),
    )
    return (
        adapter,
        {str(campaign): FAKE_CAMPAIGN},
        "documented-contract fake (no sandbox credentials)",
        graph,
    )


def run(engine: Engine, settings: Settings, seeded: Seeded) -> dict[str, Any]:
    """The loop on the seeded store: approve its pending decision, execute, restock, measure."""
    store = seeded.store_id
    label = seeded.manifest.labels[0]
    product = next(e.id for e in label.entities if e.kind.value == "product")
    campaign = next(e.id for e in label.entities if e.kind.value == "campaign")
    assert product is not None
    assert campaign is not None
    with tenant_transaction(engine, store) as conn:
        budget = conn.execute(
            text("SELECT daily_budget FROM ad_campaigns WHERE store_id = :s AND id = :c"),
            {"s": store, "c": campaign},
        ).scalar_one()
        decision = get(conn, store, seeded.decision_id)
    meta, links, meta_mode, graph = _meta(settings, campaign, budget)
    settings = settings.model_copy(update={"meta_campaign_links": links})
    if settings.approval_link_secret is None:
        settings = settings.model_copy(update={"approval_link_secret": SecretStr("demo-secret")})
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_app_settings] = lambda: settings
    client = TestClient(app, headers={"Authorization": f"Bearer {seeded.api_token}"})
    token = client.post(
        f"/api/v1/stores/{store}/decisions/{decision.decision_id}/links",
        json={"option_id": decision.recommended_option_id, "verdict": "approved"},
    ).json()["token"]
    preview = client.get(f"/api/v1/approval-links/{token}").json()  # opening it decides nothing
    approval = client.post(f"/api/v1/approval-links/{token}").json()
    replay = client.post(f"/api/v1/approval-links/{token}")
    executor = Executor(
        engine, {"simulator": SimulatorAdapter(engine), "meta": meta}, meta_links=links
    )
    executor.run_once()
    advance(engine, store, 7)  # the pause's observation window: still out of stock
    with tenant_transaction(engine, store) as conn:
        pauses = list(
            conn.execute(
                text(
                    "SELECT action_id, provider FROM actions WHERE store_id = :s AND "
                    "decision_id = :d AND rollback_of IS NULL AND status = 'executed'"
                ),
                {"s": store, "d": decision.decision_id},
            )
        )
    for pause in pauses:
        client.post(f"/api/v1/stores/{store}/actions/{pause.action_id}/rollback")
    executor.run_once()
    # The supplier delivers on the day the campaigns resume: after the pause's window.
    advance(engine, store, 7, restock=[product])
    with tenant_transaction(engine, store) as conn:
        outcomes = [measure(conn, store, p.action_id) for p in pauses]
    newest_first = client.get(f"/api/v1/stores/{store}/journal", params={"limit": 200}).json()
    journal = list(reversed(newest_first["items"]))
    final = client.get(f"/api/v1/stores/{store}/decisions/{decision.decision_id}").json()
    app.dependency_overrides.clear()
    return {
        "store": store,
        "api_token": seeded.api_token,
        "alert": seeded.incident,
        "investigation_id": seeded.investigation_id,
        "past": seeded.past,
        "decision": decision,
        "preview": preview,
        "approval": approval,
        "replay_status": replay.status_code,
        "meta_mode": meta_mode,
        "meta_calls": graph.calls if graph else None,
        "meta_mutations": graph.mutations if graph else getattr(meta, "mutations", None),
        "pauses": [(str(p.action_id), p.provider) for p in pauses],
        "outcomes": outcomes,
        "journal": journal,
        "final_status": final["status"],
    }


def markdown(r: dict[str, Any], started: datetime) -> str:
    d = r["decision"]
    rec = d.option(d.recommended_option_id)
    lines = [
        "# Demo: the stockout loop",
        "",
        f"Run {started.isoformat()} on the demo store seeded from `{SCENARIO}` "
        f"(`make demo-seed`: simulator, 14 days before the data end). Meta side: "
        f"{r['meta_mode']}.",
        "",
        "Before the loop the store has "
        + ", ".join(f"a {p.label} decision {p.outcome['status']}" for p in r["past"])
        + f", and the alert's investigation `{r['investigation_id']}`.",
        "",
        f"1. Alert: `{r['alert'].incident_id}`, level **{r['alert'].alert.value}** "
        f"({r['alert'].category.value}). Its decision `{d.decision_id}`, pending, has "
        f"{len(d.options)} options; recommended `{rec.kind}` (net-profit change over "
        f"{d.horizon_days} days, P10 / P50 / P90: {rec.p10} / {rec.p50} / {rec.p90} "
        f"{d.currency}).",
        f"2. Approved through the email link: opening it left the decision "
        f"`{r['preview']['decision']['status']}`; confirming it made it "
        f"`{r['approval']['decision']['status']}`; the same link replayed: HTTP "
        f"{r['replay_status']}.",
        f"3. Pause executed: {', '.join(f'{a} on {p}' for a, p in r['pauses'])}; Meta mutating "
        f"calls: {r['meta_mutations']}.",
        "4. Seven days later (the pause's observation window) the supplier restocks.",
        "5. Rollback requested through the API: the campaigns resume.",
        "6. Outcome of the pause (synthetic control, 7 days):",
        "",
        "| Action | Status | Effect P10 / P50 / P90 | Predicted P10 / P50 / P90 | "
        "Pre-period days, relative error, R2 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for (action, _), o in zip(r["pauses"], r["outcomes"], strict=True):
        effect = o.get("effect") or {}
        predicted = o.get("predicted") or {}
        lines.append(
            f"| `{action[:8]}` | {o['status']} ({o['reason']}) | "
            f"{effect.get('p10', '-')} / {effect.get('p50', '-')} / {effect.get('p90', '-')} | "
            f"{predicted.get('p10', '-')} / {predicted.get('p50', '-')} / "
            f"{predicted.get('p90', '-')} | {o.get('pre_days')}, {o.get('relative_error')}, "
            f"{o.get('pre_r2')} |"
        )
    lines += [
        "",
        f"7. Final decision status: `{r['final_status']}`. Journal:",
        "",
        "| At | Kind | Summary |",
        "| --- | --- | --- |",
    ]
    for e in r["journal"]:
        keys = ("status", "alert", "verdict", "channel", "kind", "provider", "reason")
        summary = ", ".join(f"{k}={e['summary'][k]}" for k in keys if e["summary"].get(k))
        lines.append(f"| {e['at'][:19]} | {e['kind']} | {summary} |")
    if r["meta_calls"] is not None:
        lines += ["", "Meta Graph API calls (fake, documented contract):", ""]
        lines += [f"- {m} /{cid} {params}" for m, cid, params in r["meta_calls"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    configure_logging("WARNING")
    started = datetime.now(UTC).replace(microsecond=0)
    engine = make_engine(prepare_database(DEMO_DB))
    settings = get_settings()
    result = run(engine, settings, seed(engine, demo_provider(settings)))
    text_ = markdown(result, started)
    (REPORT_DIR / "demo-stockout.md").write_text(text_, encoding="utf-8", newline="\n")
    sys.stdout.write(text_)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
