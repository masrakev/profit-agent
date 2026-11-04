"""The script that mirrors the demo campaigns on a Meta sandbox account
(scripts/meta_sandbox_campaigns.py), on a scripted Graph API: nothing is called without the
credentials, existing campaigns are reused, missing ones are created once, and the .env line is
printed."""

import io
import json
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from scripts import meta_sandbox_campaigns as script

CAMPAIGNS = [
    ("6433a313-4edd-55d2-a5f8-baf1fc04ed95", "Trail Jacket — Prospecting", Decimal("49.72")),
    ("ef059977-c250-5493-9b6f-2a67cd56629b", "Trail Essentials — Retargeting", Decimal("57.25")),
]


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class Graph:
    def __init__(self, existing: dict[str, str]) -> None:
        self.existing = existing
        self.created: list[dict[str, str]] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer secret-token"
        assert request.url.path == "/v25.0/act_42/campaigns"
        if request.method == "GET":
            data = [{"id": i, "name": n} for n, i in self.existing.items()]
            return httpx2.Response(200, json={"data": data})
        form = dict(httpx2.QueryParams(request.content.decode()))
        self.created.append(form)
        return httpx2.Response(200, json={"id": f"1202{len(self.created)}"})


def run(graph: Graph, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = script.main(
        list(argv),
        settings(meta_access_token=SecretStr("secret-token"), meta_ad_account_id="act_42"),
        engine=object(),  # type: ignore[arg-type]
        transport=httpx2.MockTransport(graph.handle),
        out=out,
    )
    return code, out.getvalue()


@pytest.fixture(autouse=True)
def _campaigns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "demo_campaigns", lambda engine: CAMPAIGNS)


def test_nothing_is_called_without_the_credentials() -> None:
    out = io.StringIO()
    assert script.main([], settings(meta_ad_account_id="act_42"), out=out) == 1
    assert "set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID" in out.getvalue()


def test_reuses_what_exists_creates_the_rest_and_prints_the_env_line() -> None:
    graph = Graph({"Trail Jacket — Prospecting": "120200000000009"})
    code, printed = run(graph)
    assert code == 0
    assert graph.created == [
        {
            "name": "Trail Essentials — Retargeting",
            "objective": "OUTCOME_TRAFFIC",
            "status": "ACTIVE",
            "special_ad_categories": "[]",
            "daily_budget": "5725",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        }
    ]
    line = printed.splitlines()[-1]
    assert line.startswith("META_CAMPAIGN_LINKS=")
    assert json.loads(line.removeprefix("META_CAMPAIGN_LINKS=")) == {
        CAMPAIGNS[0][0]: "120200000000009",
        CAMPAIGNS[1][0]: "12021",
    }
    assert "secret-token" not in printed


def test_a_dry_run_creates_nothing() -> None:
    graph = Graph({})
    code, printed = run(graph, "--dry-run")
    assert (code, graph.created) == (0, [])
    assert "would create Trail Jacket — Prospecting, daily budget 4972 (cents)" in printed


def test_meta_refusals_stop_it_with_their_message() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(400, json={"error": {"message": "Invalid OAuth access token"}})

    out = io.StringIO()
    code = script.main(
        [],
        settings(meta_access_token=SecretStr("secret-token"), meta_ad_account_id="act_42"),
        engine=object(),  # type: ignore[arg-type]
        transport=httpx2.MockTransport(refuse),
        out=out,
    )
    assert code == 1
    assert "Stopped: Meta answered 400: Invalid OAuth access token" in out.getvalue()
