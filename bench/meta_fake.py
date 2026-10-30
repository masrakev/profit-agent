"""A fake Meta Graph API for campaigns, following the documented contract (ADR 0017).

Not recorded from the live API (no sandbox credentials yet): it implements what the Campaign
reference documents for `GET /{id}?fields=...` and `POST /{id}` with `status`, `daily_budget`
and `execution_options=["validate_only"]`, and the Graph API error object. Failures can be
scripted per call to exercise retries, timeouts and refusals.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx2

ACCOUNT = "act_1234567890"


@dataclass
class FakeCampaign:
    status: str = "ACTIVE"
    daily_budget: int = 5000
    account_id: str = "1234567890"


@dataclass
class FakeGraph:
    campaigns: dict[str, FakeCampaign] = field(default_factory=dict)
    # Scripted outcomes for the next mutating calls: an exception to raise, or (status, body).
    failures: list[Exception | tuple[int, dict[str, Any]]] = field(default_factory=list)
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    mutations: int = 0
    on_mutation: Callable[[], None] | None = None

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        campaign_id = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            self.calls.append(("GET", campaign_id, dict(request.url.params)))
            campaign = self.campaigns.get(campaign_id)
            if campaign is None:
                return _error(400, 100, "Invalid parameter")
            return httpx2.Response(
                200,
                json={
                    "id": campaign_id,
                    "status": campaign.status,
                    "effective_status": campaign.status,
                    "daily_budget": str(campaign.daily_budget),
                    "account_id": campaign.account_id,
                },
            )
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append(("POST", campaign_id, form))
        validate = json.loads(form.get("execution_options", "[]")) == ["validate_only"]
        if not validate and self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return httpx2.Response(failure[0], json=failure[1])
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            return _error(400, 100, "Invalid parameter")
        if "status" in form and form["status"] not in ("ACTIVE", "PAUSED", "DELETED", "ARCHIVED"):
            return _error(400, 100, "Invalid parameter")
        if validate:
            return httpx2.Response(200, json={"success": True})
        if "status" in form:
            campaign.status = form["status"]
        if "daily_budget" in form:
            campaign.daily_budget = int(form["daily_budget"])
        self.mutations += 1
        if self.on_mutation is not None:
            self.on_mutation()
        return httpx2.Response(200, json={"success": True})


def _error(status: int, code: int, message: str) -> httpx2.Response:
    return httpx2.Response(
        status,
        json={
            "error": {
                "message": message,
                "type": "OAuthException",
                "code": code,
                "fbtrace_id": "AbCdEf",
            }
        },
    )


def rate_limited() -> tuple[int, dict[str, Any]]:
    return 400, {
        "error": {
            "message": "User request limit reached",
            "type": "OAuthException",
            "code": 17,
            "fbtrace_id": "x",
        }
    }


def server_error() -> tuple[int, dict[str, Any]]:
    return 500, {
        "error": {
            "message": "An unknown error occurred",
            "type": "OAuthException",
            "code": 1,
            "fbtrace_id": "x",
        }
    }


def permission_denied() -> tuple[int, dict[str, Any]]:
    return 403, {
        "error": {
            "message": "Permissions error",
            "type": "OAuthException",
            "code": 200,
            "fbtrace_id": "x",
        }
    }
