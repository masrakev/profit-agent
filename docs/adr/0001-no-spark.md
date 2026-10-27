# ADR 0001: No Apache Spark

- Status: accepted
- Date: 2026-10-27

## Context

The product analyses one e-commerce store at a time. A large independent store has tens of
thousands of orders a year, a few hundred products and a handful of ad campaigns: well under a
million rows per table per year, a few hundred MB including indexes. Our synthetic benchmark store
(120 days, 15-40 products, 3-8 campaigns) has about 7,000 order lines.

Every query we run is scoped to a single store (row-level security enforces this), so work never
needs to be distributed across machines. Accounting facts must be exact (`NUMERIC` in PostgreSQL,
see ADR 0002); statistical estimates need NumPy/SciPy-style numerics on in-memory arrays.

Spark would add a JVM, a cluster manager, serialization overhead and slow start-up to every job,
for data that fits comfortably in the memory of one process.

## Decision

- Accounting facts: computed in PostgreSQL 16 with SQL on `NUMERIC` columns.
- Estimates (response curves, simulations, causal effects): Polars, NumPy, SciPy and statsmodels
  in a single process, reading one store's data at a time.
- Jobs: Redis + arq workers; each job handles one store.

## Consequences

- Simple local development (`docker compose up`) and CI; no cluster to operate.
- Per-store work parallelises trivially by running more workers, since stores are independent.
- If we outgrow this, in order:
  1. add read replicas and partition large tables by `store_id` (and by month for order lines);
  2. move estimate jobs to Polars lazy/streaming execution or DuckDB over Parquet exports for
     out-of-core work on a single node;
  3. shard stores across PostgreSQL instances (tenancy already isolates every query);
  4. only for cross-store analytics on very large volumes, consider a distributed engine, fed from
     an append-only export of facts rather than the operational database.
