# API v1

The contract is `openapi.json` in this folder, generated from the code (`make openapi`) and
checked by a test: a change to the API is a reviewed change to that file. Decisions behind it:
ADR 0020.

## Calling it

- **Web platform**: the owner signs in with an email link. `POST /api/v1/auth/magic-links`
  sends it (the answer is the same whether or not the address has an account); the link opens
  `{APP_BASE_URL}/sign-in#token=...`, whose page posts the token to `POST /api/v1/auth/sessions`.
  That sets an HTTP-only session cookie and returns a `csrf_token`: every state-changing request
  (POST, PUT, PATCH, DELETE) sends it back in `X-CSRF-Token`.
- **Programs**: `Authorization: Bearer pa_...`, a store's API token
  (`POST /api/v1/stores/{store_id}/api-tokens`, signed-in owners only, shown once).
- A store that is not the caller's is answered `404`, as if it did not exist.

## Conventions

- Errors are RFC 9457 problem details (`application/problem+json`): `type`, `title`,
  `status`, `detail`, a stable `code` and the `request_id`.
- Every response has an `X-Request-ID` (send your own, 8-64 characters `[A-Za-z0-9._-]`, to
  trace a call).
- Lists are pages: `?limit=` (1-200, default 50) and `?cursor=` (the previous page's
  `next_cursor`; null on the last page).
- Rate limits per client address (stricter on sign-in) and per store: `429` with `Retry-After`.
- Numbers are facts: text cites them as `{{F<id>}}` and entities as `{{E:...}}`; responses
  carry the cited `facts` (with a `formatted` value) and the raw `names` (escape them).
- Streams are server-sent events (`text/event-stream`): `event: step` per agent step, then
  `answer` (Ask), `done` or `failed`. A reconnecting client sends `Last-Event-ID`.

## Problem codes

| Code | Status | Meaning |
| --- | --- | --- |
| `unauthenticated` | 401 | No session or token, or it is not valid any more |
| `csrf` | 403 | A cookie request that changes state without the CSRF token, or from another origin |
| `forbidden` | 403 | Allowed callers only (a token cannot create tokens; the admin switch) |
| `not_found` | 404 | No such resource, or not one of the caller's stores |
| `invalid_request` | 422 | The request does not validate (`errors` lists the fields) |
| `invalid_cursor` | 422 | The cursor is not one this API issued |
| `invalid_link`, `expired_link`, `used_link` | 401 or 403, 410, 409 | Sign-in links (401) or approval links (403): not valid, expired, already used |
| `already_decided`, `expired` | 409 | A decision is decided once, before it expires |
| `superseded` | 409 | Another pending decision on the same campaign or product, on more recent data, superseded it (`superseded_by`) |
| `unknown_option`, `not_executable` | 404, 422 | The option is not one of the decision's, or cannot run |
| `invalid_goal` | 422 | A goal's metric, target or deadline cannot be taken (the deadline within six months) |
| `not_confirmed` | 409 | The goal is a draft: confirm the restated goal first |
| `conflict`, `no_data` | 409 | The plan is not the one to accept (already accepted or superseded); the store has no data to forecast |
| `rate_limited` | 429 | Too many requests: retry after `Retry-After` seconds |
| `not_ready` | 503 | The database does not answer (readiness) |
| `internal_error` | 500 | Unexpected: quote the `request_id` |

## Endpoints

| Method | Path | What |
| --- | --- | --- |
| GET | `/api/v1/health` | The process answers |
| GET | `/api/v1/ready` | The database answers |
| POST | `/api/v1/auth/magic-links` | Email a sign-in link |
| POST | `/api/v1/auth/sessions` | Open a session from a link's token |
| GET | `/api/v1/auth/session` | Who is calling, and their stores |
| DELETE | `/api/v1/auth/session` | Sign out |
| POST, GET | `/api/v1/stores/{store_id}/api-tokens` | Create (once shown) or list API tokens |
| DELETE | `/api/v1/stores/{store_id}/api-tokens/{token_id}` | Revoke a token |
| GET | `/api/v1/stores/{store_id}/overview` | Health line, money at stake, top items, pending decisions |
| GET | `/api/v1/stores/{store_id}/incidents` | Incidents of the latest detection run, most urgent first |
| GET | `/api/v1/stores/{store_id}/incidents/{incident_id}` | An incident, its facts, investigations and decisions |
| POST | `/api/v1/stores/{store_id}/incidents/{incident_id}/investigations` | Start an investigation (202) |
| GET | `/api/v1/stores/{store_id}/investigations/{investigation_id}/events` | Its steps, streamed while it runs |
| GET | `/api/v1/stores/{store_id}/investigations/{investigation_id}/steps` | Its step trace (30 days) |
| GET | `/api/v1/stores/{store_id}/investigations/{investigation_id}` | The verified investigation |
| POST | `/api/v1/stores/{store_id}/incidents/{incident_id}/investigate` | Investigate and wait for the result |
| GET | `/api/v1/stores/{store_id}/facts/{fact_id}` | A number: formula, parent facts, source rows |
| GET | `/api/v1/stores/{store_id}/profit-bridge` | The change in net profit by driver (`?period=week` or `month`) |
| GET | `/api/v1/stores/{store_id}/briefings` | Briefings, newest first (`?kind=`) |
| GET | `/api/v1/stores/{store_id}/briefings/{briefing_id}` | A briefing as sent |
| POST | `/api/v1/stores/{store_id}/ask` | Ask, and wait for the answer contract |
| POST | `/api/v1/stores/{store_id}/ask/stream` | Ask, streamed |
| POST, GET | `/api/v1/stores/{store_id}/goals` | Set a goal (a draft, restated until the owner confirms it), or list goals |
| GET | `/api/v1/stores/{store_id}/goals/{goal_id}` | A goal, its restatement and its facts |
| POST | `/api/v1/stores/{store_id}/goals/{goal_id}/confirm` | Confirm it: its feasibility |
| GET | `/api/v1/stores/{store_id}/goals/{goal_id}/feasibility` | Probability, verdict, gap; past 90 days a probability range and quarterly checkpoints, no point |
| POST | `/api/v1/stores/{store_id}/goals/{goal_id}/explain` | Confirm it and answer with its feasibility or its plan (`what`), in the Ask answer contract |
| POST, GET | `/api/v1/stores/{store_id}/goals/{goal_id}/plans` | Propose a plan, or list its plans |
| POST | `/api/v1/stores/{store_id}/goals/{goal_id}/plans/{plan_id}/accept` | Accept it: its steps due today become decisions to approve |
| GET | `/api/v1/stores/{store_id}/goals/{goal_id}/progress` | Weekly tracking and monthly re-forecasts |
| POST | `/api/v1/stores/{store_id}/goals/{goal_id}/revise` | A new target or deadline: confirmed again, plans superseded |
| GET, PUT | `/api/v1/stores/{store_id}/settings` | The store's settings (every change audited) |
| GET, PUT | `/api/v1/stores/{store_id}/kill-switch` | Read or set the store's kill switch |
| GET | `/api/v1/stores/{store_id}/decisions` | Decisions, newest first |
| GET | `/api/v1/stores/{store_id}/decisions/{decision_id}` | A decision and its options |
| POST | `/api/v1/stores/{store_id}/decisions/{decision_id}/approve` | Approve an option |
| POST | `/api/v1/stores/{store_id}/decisions/{decision_id}/reject` | Reject the decision |
| POST | `/api/v1/stores/{store_id}/decisions/{decision_id}/links` | A signed approval link (for email) |
| GET | `/api/v1/approval-links/{token}` | What a link would decide (changes nothing) |
| POST | `/api/v1/approval-links/{token}` | Confirm it: decide, once |
| POST | `/api/v1/stores/{store_id}/actions/{action_id}/rollback` | Undo an executed action |
| GET | `/api/v1/stores/{store_id}/journal` | Incidents, decisions, approvals, actions, outcomes |
| POST | `/api/v1/stores/{store_id}/policy/preview` | What the policy engine would decide |
| GET | `/api/v1/stores/{store_id}/trust` | The trust ledger |
| GET | `/api/v1/stores/{store_id}/export` | Everything the store has: a zip of JSON Lines, one file per table, no secrets |
| DELETE | `/api/v1/stores/{store_id}` | Delete the store and all its data, for good (signed-in owner, body `confirm_store_id`) |
| GET | `/api/v1/stores/{store_id}/connections` | Its Meta and Shopify connections (account and key id, never the token) |
| PUT, DELETE | `/api/v1/stores/{store_id}/connections/{provider}` | Save a platform token (encrypted at rest) or remove it |
| PUT | `/api/v1/admin/kill-switch` | Stop every action of every store (admin token) |

Goals (ADRs 0023, 0024): a goal question to `POST /ask` comes back with `status`
`confirmation` and the draft's `goal_id`; the owner confirms with `POST /goals/{goal_id}/explain`
(or `/confirm` for the numbers alone). Plans never execute anything: their steps become
decisions in the normal flow.

Privacy (ADR 0021): the export and the deletion cover every table with a `store_id`, found when
they run; a deletion is recorded outside the store's data (who, when, rows per table). Model
traces (investigation steps) are deleted after 30 days.
