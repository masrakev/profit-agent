"""Meta Marketing API adapter: pause, resume and daily budget of a campaign (ADR 0017).

Following the Campaign reference (Graph API v25.0, read before writing this):

- update: `POST /{campaign_id}` with `status` (`ACTIVE` or `PAUSED`) and/or `daily_budget`
  (int64, in the ad account currency's minimum denomination: cents for USD);
- dry run: the same call with `execution_options=["validate_only"]`, which runs the validation
  rules without mutating and answers `{"success": true}`;
- read back: `GET /{campaign_id}?fields=status,effective_status,daily_budget,account_id`
  (`daily_budget` comes back as a numeric string);
- errors: a JSON `error` object with `message`, `type`, `code`, `error_subcode`, `fbtrace_id`.
  Codes 1, 2, 4, 17 and 341 are temporary (wait and retry, Graph API error handling guide),
  613 and 80004 are rate limits (Campaign reference); 5xx and timeouts are retried too.

Safety: the adapter only touches campaigns of the configured ad account (the sandbox account
for the demo): every call reads `account_id` first and refuses another account. The access
token is sent as a bearer header and never logged.
"""

import json
from typing import Any

import httpx2

from app.executor.adapters import AdapterError, CampaignRef, CampaignState, Change

GRAPH_URL = "https://graph.facebook.com"
API_VERSION = "v25.0"
RETRYABLE_CODES = frozenset({1, 2, 4, 17, 341, 613, 80004})


class MetaAdsAdapter:
    name = "meta"

    def __init__(
        self,
        *,
        access_token: str,
        ad_account_id: str,
        transport: httpx2.BaseTransport | None = None,
        base_url: str = GRAPH_URL,
        api_version: str = API_VERSION,
        timeout_s: float = 10.0,
    ) -> None:
        self.ad_account_id = ad_account_id.removeprefix("act_")
        self._client = httpx2.Client(
            base_url=f"{base_url}/{api_version}",
            transport=transport,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.mutations = 0  # successful mutating calls (red team: duplicate executions)

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx2.TimeoutException as exc:
            raise AdapterError("Meta API timeout", retryable=True, code="timeout") from exc
        except httpx2.TransportError as exc:
            raise AdapterError(
                f"Meta API unreachable: {type(exc).__name__}", retryable=True
            ) from exc
        try:
            body: dict[str, Any] = response.json()
        except json.JSONDecodeError:
            body = {}
        error = body.get("error") if isinstance(body, dict) else None
        if response.status_code >= 400 or error:
            code = int(error.get("code", 0)) if isinstance(error, dict) else 0
            message = str(error.get("message", "")) if isinstance(error, dict) else ""
            retryable = response.status_code >= 500 or code in RETRYABLE_CODES
            raise AdapterError(
                f"Meta API error {response.status_code} code {code}: {message[:200]}",
                retryable=retryable,
                code=str(code),
            )
        return body

    def _owned(self, campaign: CampaignRef) -> dict[str, Any]:
        body = self._call(
            "GET",
            f"/{campaign.external_id}",
            params={"fields": "status,effective_status,daily_budget,account_id"},
        )
        if str(body.get("account_id", "")).removeprefix("act_") != self.ad_account_id:
            raise AdapterError(
                "the campaign does not belong to the configured ad account", retryable=False
            )
        return body

    def read(self, campaign: CampaignRef) -> CampaignState:
        body = self._owned(campaign)
        status = str(body.get("status", ""))
        if status not in ("ACTIVE", "PAUSED"):
            raise AdapterError(f"unexpected campaign status {status!r}", retryable=False)
        budget = body.get("daily_budget")
        return CampaignState(
            status=status,  # type: ignore[arg-type]
            daily_budget_minor=int(budget) if budget not in (None, "") else None,
        )

    def _form(self, change: Change) -> dict[str, str]:
        form: dict[str, str] = {}
        if change.status is not None:
            form["status"] = change.status
        if change.daily_budget_minor is not None:
            form["daily_budget"] = str(change.daily_budget_minor)
        return form

    def validate(self, campaign: CampaignRef, change: Change) -> None:
        self._owned(campaign)
        form = {**self._form(change), "execution_options": json.dumps(["validate_only"])}
        body = self._call("POST", f"/{campaign.external_id}", data=form)
        if body.get("success") is not True:
            raise AdapterError("validation did not succeed", retryable=False)

    def apply(self, campaign: CampaignRef, change: Change) -> None:
        self._owned(campaign)
        body = self._call("POST", f"/{campaign.external_id}", data=self._form(change))
        if body.get("success") is not True:
            raise AdapterError("the update did not succeed", retryable=False)
        self.mutations += 1
