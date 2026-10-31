# ADR 0021: Privacy: export, deletion, retention and encrypted platform tokens

- Status: accepted
- Date: 2026-10-31

## Context

The launch readiness review (section 3) promises that an owner can take all of their store's
data and have all of it deleted, with the deletion recorded; that model traces are kept 30
days; and that the access tokens the product holds for Meta and Shopify are encrypted at rest.
Data is spread over more than thirty tenant tables, and new ones keep arriving. A list of
tables written by hand would silently miss the next one.

## Decision

**Export** (`backend/app/privacy/export.py`, `GET /stores/{id}/export`). A zip with one JSON
Lines file per tenant table: every public table with a `store_id` column, found at run time and
read under the store's row-level security, streamed row by row. `access.json` lists the store's
owners and its API tokens (name, prefix, dates); `manifest.json` gives the format version and
the row count per table, and names what is left out on purpose: token digests and the
encrypted platform tokens. The export is audited (`store.exported`).

**Deletion** (`backend/app/privacy/deletion.py`, migration 0013, `DELETE /stores/{id}`). A
signed-in owner only (not an API token), with the store's own id repeated in the body. The
database part is one function, `delete_store(target uuid, actor text)`:

- `SECURITY DEFINER` with a fixed `search_path`, no free-form arguments, no PUBLIC grant, and
  it refuses to run unless `app.store_id` is the target: only inside that store's own tenant
  transaction, so one store's session cannot delete another;
- deletes the store's rows from every public table with a `store_id` (found at run time),
  retrying in passes when a foreign key blocks a parent before its children (at most 25), then
  the store itself; owner memberships and API tokens cascade from it;
- records the deletion in `control.store_deletions`: the store id, who asked, the number of
  rows deleted per table, and the last hash of the store's audit chain. The store's own audit
  log is deleted with everything else, so the record lives outside the tenant tables and holds
  no store content.

Outside the database, recorded model exchanges (cassettes) that name the store are removed.
Model traces are in `investigation_steps`, deleted with the rest; the spend ledger names no
store. The proof is a test (`test_deleting_a_store_leaves_nothing`): after the API call, every
public table with a `store_id` (at least 30) and the access tables hold no row of the store, the
deletion record matches the rows reported, the store's cassette is gone, and another store is
untouched.

**Retention** (`backend/app/privacy/retention.py`, scheduler job `retention`, daily at 03:17
UTC). For each store, in its own tenant transaction: agent step traces older than 30 days
(`MODEL_TRACE_RETENTION_DAYS`) are deleted; the verified investigations they led to stay, like
facts, decisions and the audit log. Expired sign-in links and sessions are deleted too.

**Platform tokens** (`backend/app/privacy/crypto.py`, `connections.py`, table
`store_connections`; `PUT`, `GET`, `DELETE /stores/{id}/connections/{provider}`). Envelope
encryption with AES-256-GCM: each token gets its own random data key, which encrypts it; the
master key, from the environment (`TOKEN_ENCRYPTION_KEY`, 32 bytes base64url, with its id
`TOKEN_ENCRYPTION_KEY_ID`), wraps the data key. Both encryptions bind the store, the provider
and the part as associated data, so a ciphertext copied to another store or provider does not
decrypt. Rotating the master key re-wraps data keys; tokens stay as they are. A token is
opened only where it is used, the executor's Meta adapter for that store, and is never returned
by the API or exported.

## Consequences

- Deletion cannot be undone; the owner confirms with the store id, and the API answers with the
  number of rows deleted per table.
- A new tenant table is exported and deleted without any change to this code. A table that
  holds store data without a `store_id` column would be missed by both: the schema rule that
  every tenant table carries `store_id` (and row-level security) is what this relies on.
- Database backups are not covered: their retention is the hosting provider's and must stay
  within the 30-day target of section 3.
- Losing the master key loses the platform tokens, not the store's data: owners reconnect.
  Without `TOKEN_ENCRYPTION_KEY` the product refuses to store a token rather than store it in
  clear.
- `control.store_deletions` keeps, after deletion, that a store existed, when it was deleted and
  by whom; nothing else.
