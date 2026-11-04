"""Mirror the demo store's campaigns on a Meta sandbox ad account, once (ADR 0017).

    uv run python scripts/meta_sandbox_campaigns.py            # creates what is missing
    uv run python scripts/meta_sandbox_campaigns.py --dry-run  # says what it would create

Needs, in `.env`: META_ACCESS_TOKEN (with `ads_management` on the sandbox account) and
META_AD_ACCOUNT_ID (`act_<id>`), and the demo store seeded (`make demo-seed`). For each of the
demo store's campaigns it finds the sandbox campaign of the same name, or creates it (active,
with the same daily budget, a traffic objective), then prints the line to put in `.env`:

    META_CAMPAIGN_LINKS={"<demo campaign id>": "<sandbox campaign id>", ...}

Running it again creates nothing new. The sandbox delivers no ads and spends nothing; the
executor then pauses, resumes and changes budgets there, and reads them back. The token is sent
as a bearer header and never printed.
"""

import argparse
import json
import sys
from decimal import Decimal
from typing import Any, TextIO

import httpx2
from sqlalchemy import Engine, create_engine, text

from app.config import Settings, get_settings
from app.executor.meta import API_VERSION, GRAPH_URL
from bench.demo_seed import DEMO_DB
from bench.runner.__main__ import _with_db


def demo_campaigns(engine: Engine) -> list[tuple[str, str, Decimal]]:
    """The demo store's campaigns: id, name and daily budget, by name."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, daily_budget FROM ad_campaigns ORDER BY name")
        ).all()
    return [(str(r.id), str(r.name), Decimal(r.daily_budget)) for r in rows]


def _call(client: httpx2.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = client.request(method, path, **kwargs)
    body: dict[str, Any] = response.json() if response.content else {}
    error = body.get("error")
    if response.status_code >= 400 or error:
        message = error.get("message", "") if isinstance(error, dict) else response.text
        raise RuntimeError(f"Meta answered {response.status_code}: {str(message)[:300]}")
    return body


def mirror(
    client: httpx2.Client,
    account: str,
    campaigns: list[tuple[str, str, Decimal]],
    *,
    dry_run: bool,
    out: TextIO,
) -> dict[str, str]:
    """The sandbox campaign of each demo campaign, created when missing."""
    existing = _call(
        client, "GET", f"/act_{account}/campaigns", params={"fields": "id,name", "limit": "200"}
    )
    by_name = {c["name"]: c["id"] for c in existing.get("data", [])}
    links: dict[str, str] = {}
    for campaign_id, name, budget in campaigns:
        if name in by_name:
            out.write(f"  found    {name}: {by_name[name]}\n")
            links[campaign_id] = by_name[name]
            continue
        minor = str(int(budget * 100))  # the account currency's cents
        if dry_run:
            out.write(f"  would create {name}, daily budget {minor} (cents)\n")
            continue
        created = _call(
            client,
            "POST",
            f"/act_{account}/campaigns",
            data={
                "name": name,
                "objective": "OUTCOME_TRAFFIC",
                "status": "ACTIVE",
                "special_ad_categories": "[]",
                "daily_budget": minor,
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            },
        )
        out.write(f"  created  {name}: {created['id']}\n")
        links[campaign_id] = str(created["id"])
    return links


def main(
    argv: list[str] | None = None,
    settings: Settings | None = None,
    engine: Engine | None = None,
    transport: httpx2.BaseTransport | None = None,
    out: TextIO = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description="Mirror the demo campaigns on a Meta sandbox")
    parser.add_argument("--dry-run", action="store_true", help="say what would be created")
    args = parser.parse_args(argv)
    settings = settings or get_settings()
    if settings.meta_access_token is None or not settings.meta_ad_account_id:
        out.write("Nothing done: set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID in .env\n")
        return 1
    engine = engine or create_engine(_with_db(settings.database_url, DEMO_DB))
    campaigns = demo_campaigns(engine)
    if not campaigns:
        out.write("Nothing done: the demo store has no campaigns (run make demo-seed)\n")
        return 1
    account = settings.meta_ad_account_id.removeprefix("act_")
    token = settings.meta_access_token.get_secret_value()
    with httpx2.Client(
        base_url=f"{GRAPH_URL}/{API_VERSION}",
        transport=transport,
        timeout=20.0,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        out.write(f"Sandbox account act_{account}:\n")
        try:
            links = mirror(client, account, campaigns, dry_run=args.dry_run, out=out)
        except (RuntimeError, httpx2.HTTPError) as exc:
            out.write(f"Stopped: {exc}\n")
            return 1
    if args.dry_run:
        return 0
    out.write("\nPut this line in .env:\n")
    out.write(f"META_CAMPAIGN_LINKS={json.dumps(links, ensure_ascii=False)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
