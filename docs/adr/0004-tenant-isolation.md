# ADR 0004: Tenant isolation with PostgreSQL row-level security

- Status: accepted
- Date: 2026-10-27

## Context

The product is multi-tenant: one database holds many stores. A missing `WHERE store_id = ...` in
application code must not leak or corrupt another store's data.

## Decision

- Every table has `store_id`. Row-level security is enabled and forced on every table with one
  policy: `store_id = NULLIF(current_setting('app.store_id', true), '')::uuid` for both reads
  (`USING`) and writes (`WITH CHECK`).
- The application connects as `profit_app`: `NOSUPERUSER NOBYPASSRLS`, without ownership of any
  table. Migrations run as the owner role.
- Each unit of work runs in `tenant_transaction`, which sets `app.store_id` with
  `set_config(..., is_local => true)`: the setting dies with the transaction, so a pooled
  connection cannot carry a tenant over to the next request. Without a tenant, no row is visible.
- Child tables reference parents through composite foreign keys `(store_id, id)`, so a row can
  never point at another store's row even if a policy were misconfigured.
- `facts`, `fact_lineage` and `audit_log` are append-only for the application role (no UPDATE or
  DELETE privilege); the audit log is also hash-chained.

## Consequences

- Isolation is enforced by the database and covered by tests (read, write, update, delete and
  cross-store references).
- `COPY FROM` is unavailable on RLS tables; bulk loads use multi-row `INSERT`.
- Planner statistics on `store_id` lag behind bulk loads: right after a large store is loaded the
  planner believes it has one row and chose nested loops that took 25 s for a single fact query.
  `ANALYZE` needs the owner on PostgreSQL 16, so a `SECURITY DEFINER` function
  `refresh_planner_statistics()` (no arguments, EXECUTE granted only to the app role) is called
  after bulk loads. Ingestion jobs must call it too.
- Cross-store work (admin, benchmarks across stores) must go through an explicit owner
  connection, never the application role.
