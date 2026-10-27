# ADR 0002: Exact money in SQL; floats only for estimates

- Status: accepted
- Date: 2026-10-27

## Context

The product's promise is that every number shown to a store owner is verifiable. Binary floats
cannot represent most decimal amounts (0.1 + 0.2 != 0.3), so float sums of many order lines drift
and differ by summation order. Accounting values must reconcile to the cent with the store's own
records, and recomputing them must give bit-identical results so fact hashes are stable.

## Decision

- Money is stored as `NUMERIC(18,4)` with an ISO 4217 `currency` column on every row that holds
  an amount. In Python it is always `Decimal`; Pydantic models enforce at most 4 decimal places.
- `exact` facts (revenue, costs, margins, spend, ...) are aggregated by PostgreSQL in SQL over
  `NUMERIC` columns. The same statement returns the contributing row ids (lineage) and a SHA-256
  digest of the rows' relevant columns (inputs hash), so value and lineage come from one snapshot.
- Facts derived from other facts use `Decimal`:
  - sums and differences under a context that traps `Inexact` and `Rounded`, so a derived exact
    fact is provably the exact arithmetic of its parents;
  - ratios use one division rounded `ROUND_HALF_EVEN` to 28 significant digits. A zero denominator
    yields an `undefined` fact with a reason, never an exception or an infinity.
- Order-level payment fees are allocated to lines at write time in 0.0001 units with the
  largest-remainder method, so product-level and store-level fees reconcile exactly.
- Values are stored unrounded (`facts.value` is unconstrained `NUMERIC`). Rounding happens only at
  presentation, `ROUND_HALF_EVEN`.
- Floats are allowed only for `estimate` facts (statistical outputs), which always carry
  P10/P50/P90 and a method name, and in the synthetic generator's internal simulation (every amount
  it writes is quantized to `Decimal` cents). Hashed payloads (facts, audit log) reject floats.

### LLM output is structured; our code builds the layout

- Models never return free-form markdown documents. They return JSON validated against a Pydantic
  schema (for example a list of findings, each with a short `claim` and `evidence` text, and the
  fact ids it relies on).
- Lists, tables, headings and numbering are produced by our code from that structure. Numbers in
  them come only from rendered facts.
- The verifier checks every free-text field before rendering. Each field must reference facts as
  `{{F<id>}}`; any other numeric literal (amounts, percentages, ratios, multiplicative words such
  as "doubled" or "3x", spelled-out numbers) rejects the output.
- As a fallback for prose that does contain lists, ordered-list markers at the start of a line
  are accepted only while they count 1, 2, 3..., so a marker cannot smuggle in a number.

## Consequences

- Golden tests can assert exact equality, or equality to the cent where a division is involved.
- The same inputs always produce the same fact hash; recomputation is idempotent.
- Multi-currency stores need explicit conversion facts later: today a money fact over rows in a
  currency other than the store's is `undefined` with a reason.
- SQL aggregates are slightly more verbose than a dataframe pipeline; we accept that for
  exactness.
