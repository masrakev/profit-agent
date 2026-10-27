# ADR 0003: Fact lineage stored as one id array per source table

- Status: accepted
- Date: 2026-10-27

## Context

Every fact records its lineage: the source rows it aggregates, or the parent facts it derives
from. A store-level revenue fact over 120 days references thousands of order lines, and a full
recompute produces about 250 facts. One lineage row per source id meant ~76,000 inserts per
recompute, each paying a foreign-key and row-level-security check.

## Decision

`fact_lineage` holds one row per parent fact (`parent_fact_id`, with a `role` such as `revenue`),
or one row per source table with every contributing id in `source_ids uuid[]`. Lineage rows are
written over psycopg's binary protocol, one statement per row (psycopg's pipelined `executemany`
was several times slower with Docker Desktop on Windows).

## Consequences

- A full recompute of the benchmark store persists in about 1.5 s locally instead of ~10 s.
- Finding the facts that use a given source row needs `WHERE :id = ANY(source_ids)`; add a GIN
  index if that query becomes frequent.
- The inputs hash, not the lineage, guarantees reproducibility: it is a SHA-256 of the
  contributing rows' relevant columns, computed in the same SQL statement as the value.
