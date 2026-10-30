# ADR 0017: Executor, platform adapters and the Meta sandbox

- Status: accepted (live Meta sandbox run pending: no credentials yet)
- Date: 2026-10-30

## Context

Approved actions must run exactly once on the platform, survive crashes and platform errors,
and leave a complete record. The demo executes on a Meta sandbox ad account; benchmark and
golden scenarios need the same actions on synthetic stores so their outcomes can be measured.

## Decision

**One adapter interface** (`backend/app/executor/adapters.py`): read a campaign's state
(status, daily budget in the currency's minor unit), validate a change (dry run), apply it.

**Meta adapter** (`backend/app/executor/meta.py`), written from the Marketing API Campaign
reference (Graph API v25.0): `POST /{campaign_id}` with `status` (`ACTIVE` | `PAUSED`) and
`daily_budget` (int, minimum denomination of the account currency: cents for USD); the dry run
is the same call with `execution_options=["validate_only"]`; the read-back is
`GET /{campaign_id}?fields=status,effective_status,daily_budget,account_id`. Errors are the Graph
API `error` object; codes 1, 2, 4, 17, 341 (Graph API error guide), 613 and 80004 (rate limits,
Campaign reference), 5xx and timeouts are retried; others fail. Every call first checks the
campaign's `account_id` against the configured ad account and refuses any other account. The
token travels as a bearer header and is never logged. Credentials and the mapping of our
campaigns to sandbox campaigns come from `.env` (`META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`,
`META_CAMPAIGN_LINKS`). They are not configured yet: the adapter is tested against a fake that
implements the documented contract (`bench/meta_fake.py`), not a recording, and the live
pause/resume round trip is pending. The sandbox documentation pages could not be retrieved
(404); nothing here depends on sandbox-specific behaviour beyond the Campaign endpoints.

**Simulator adapter** (`backend/app/executor/simulator.py`): the same changes on a synthetic
store (its campaign row) recorded as events at the simulator's day; `bench/simulator.py` turns
events into generator interventions and appends the days that follow, so actions have real
outcomes. A synthetic store whose campaign is linked to a sandbox campaign executes on Meta and
mirrors the change on the simulator (the demo).

**Worker** (`backend/app/executor/worker.py`), per outbox row:

1. claim in a short transaction: `SELECT ... FOR UPDATE SKIP LOCKED` within the store's tenant
   transaction, the policy verdict (audited), then a 5-minute lease (the row stays pending but
   invisible), the action marked executing;
2. on the platform, outside any transaction: read the state, dry run, apply, read back (it
   must match the target);
3. finish in one transaction: action executed with its before and after states (and the day it
   took effect), outbox row done, audit entry, decision executed when all its actions are.

A crash between 2 and 3 leaves the row leased; when the lease ends it is claimed again, the
platform's state already matches the target, so nothing is applied twice and the audit is
written then (`already_applied: true`). Retryable failures back off exponentially with jitter
(30 s doubling, 5 attempts); others fail the action and its decision, audited. Each provider has
a circuit breaker.

**Rollback**: pause <-> resume, a budget restored to its value before the action; requested by
the owner (the request is the approval), queued through the outbox like any action, exempt
from the one-change-per-day rule but not from the kill switches.

## Consequences

- Duplicate executions are prevented twice: a unique idempotency key per action, and
  read-before-write on retry.
- No network call holds a database transaction open.
- Until sandbox credentials are set, "executed on Meta" means executed against the documented
  contract; the demo report states which one ran.
