# ADR 0020: Authentication and API conventions

- Status: accepted
- Date: 2026-10-31

## Context

The web platform and the owner's own programs call the API for real stores. Until Task 5 the
API trusted a store id in a header and an actor name sent by the client. Before a merchant
connects a store, every request must say who calls, every store route must be scoped to the
caller's stores, and the contract the frontend is built on must stop moving silently.

## Decision

**Owners sign in by email link** (`backend/app/auth/service.py`, `backend/app/api/auth.py`,
migration 0011, schema `auth`). No passwords are stored.

- `POST /auth/magic-links` sends a link with a random token (`secrets.token_urlsafe(32)`),
  valid 15 minutes and used once: it is consumed by one conditional `UPDATE`, so two clicks
  cannot both open a session. At most 5 links per address per hour. The answer is the same
  whether or not the address has an account, so the route says nothing about who is a
  customer. The token travels in the URL fragment of the platform's sign-in page, so it never
  reaches a server log.
- `POST /auth/sessions` exchanges the token for a session: a random session token in the
  `pa_session` cookie (HTTP-only, Secure, SameSite=Lax, path `/api`, 14 days) and a random CSRF
  token, returned in the body and in the `pa_csrf` cookie the page can read. `DELETE
  /auth/session` revokes it.
- Sign-in tokens, session tokens, CSRF tokens and API tokens are stored only as SHA-256
  digests, compared in constant time.

**CSRF.** A state-changing request (POST, PUT, PATCH, DELETE) made with the session cookie
must send the session's CSRF token in `X-CSRF-Token` and, when the browser sends an `Origin`,
come from the platform's origin (`APP_BASE_URL`). Otherwise: 403 `csrf`.

**API tokens for programs.** `Authorization: Bearer pa_...`: one store's token, created by a
signed-in owner (`POST /stores/{id}/api-tokens`), shown once, listed by prefix and revoked by
id. A bearer request carries no cookie, so it needs no CSRF token. A token cannot create
tokens, and only a signed-in owner can delete a store.

**Every store route is scoped.** Each route under `/stores/{store_id}` depends on `StoreDep`:
the store must be one of the caller's (an owner's memberships, or the token's own store). A
store that is not is answered 404 `not_found`, as if it did not exist, so ids of other stores
reveal nothing. A test calls every `{store_id}` route of the live schema with another store's
credentials (404) and with none (401). Decisions, approvals and rollbacks record who acted from
the principal (`owner:<email>` or `token:<name>`); the client-supplied `X-Actor` header is gone.

**Conventions** (`docs/api/README.md`):

- Errors are RFC 9457 problem details (`application/problem+json`): `type`
  `urn:profit-agent:problem:<code>`, `title`, `status`, `detail`, the `request_id`, and `errors`
  for invalid requests. Codes are a closed list, documented.
- Request ids: a valid incoming `X-Request-ID` is kept, otherwise one is made; it is in the
  response, in problem bodies and in every log line of the request.
- Security headers on `/api` responses: `nosniff`, `DENY` framing, no referrer, a CSP that
  loads nothing, HSTS, `no-store` caching, same-origin resource policy.
- Rate limits, fixed one-minute windows: 120 requests per client address, 10 on the sign-in
  routes, 600 per store; over a limit, 429 with `Retry-After`.
- Lists are cursor-paginated: `limit` (1 to 200, default 50) and an opaque `cursor` (the last
  item's sort key, base64url JSON); a cursor the API did not issue is 422
  `invalid_cursor`. Pages stay stable when new items arrive.
- `GET /health` (the process answers) and `GET /ready` (the database answers).
- Investigation steps and Ask answers stream as server-sent events; a client that reconnects
  with `Last-Event-ID` resumes after the last step it saw.

**A frozen contract.** `make openapi` writes `docs/api/openapi.json`; a test fails when the live
schema differs from the committed file, so every API change is reviewed with its contract.

## Consequences

- An owner's mailbox is their account: whoever controls it can sign in. Two-factor sign-in is
  not built.
- Rate-limit counters live in the API process: one process per deployment for now; several
  processes need a shared counter store (Redis) to keep the same limits.
- API tokens cannot be recovered, only revoked and replaced; a leaked token is limited to one
  store and cannot mint others or delete the store.
- The frontend can be built against `openapi.json` without reading backend code; changing the
  API means regenerating the file in the same commit.
