# ADR 0013: Token and cost management

- Status: accepted
- Date: 2026-10-29

## Context

An investigation is a multi-turn tool loop: every turn resends the whole conversation, so input
tokens grow with each tool result, and reasoning models add hidden output tokens. Uncontrolled,
one investigation can cost dollars; the target is a mean below $0.50 at production routing
(SPEC section 12), and the benchmark runs hundreds of them on a $25 budget. Costs must also be
reported honestly: a benchmark on the cheaper Contributor model must still say what production
would pay.

## Decision

**Per-stage configuration** in `backend/app/agent/stages.toml` (ADR 0011): model, reasoning
effort, output-token cap, tool-call cap and cumulative input-token cap per stage, plus the
per-tool-result size limit. The file has a `version` and a content digest; both are part of the
investigation cache key, so a config change never serves a stale investigation.

**Cache-friendly layout.** Every request of a loop starts with the same prefix: the system prompt,
the tool schemas and the structured-output format (fixed per prompt version), then the store
context (stable per store), then the incident or question, then the turns. `prompt_cache_key`
defaults to `model:purpose:prompt_version`, so requests of the same kind hit the provider's
prompt cache. Cached input tokens are reported per call and per stage (cache hit rate).

**Compact tool results.** Tool results are JSON views with ids instead of text; a result longer
than the limit (12,000 characters) is cut by halving its longest lists until it fits, and the
cut is marked explicitly (`{"truncated": true, "note": "... narrow the query"}`) so the model
knows to ask a narrower question rather than assume completeness.

**Memoised calls.** Within one loop, a repeated call (same tool, same validated arguments) is
answered from a memo and costs no database work; memo hits are counted.

**Investigation cache.** A finished investigation is stored with a key over: the investigation
format version, the incident id, the hashes of every fact the incident cites (symptoms,
attribution, impact), the prompt version, the model, the reasoning effort and the stage-config
version and digest. A new request with the same key returns the stored investigation without a
model call; any change in the data, prompt, model or configuration misses. Partial
investigations are never served from the cache.

**Budgets.**

- The budget guard (ADR 0009) reserves each call's worst-case cost before sending it: every
  input token uncached, every output token used. It never counts on a cache hit, so a cap holds
  even when the provider's cache is cold. Caps: per run, per UTC day, and a total cap per task.
- Per stage: when the tool-call cap is reached the model must answer with what it has; when the
  cumulative input-token cap is reached the loop stops and the investigation is stored as
  `partial`, built from the facts already gathered, with the stop reason. Partial results are
  verified like any other.

**Reporting.** Every call records model, input, cached, output and reasoning tokens, latency and
exact cost from a versioned price table (`prices_v1.toml`). Investigations and Ask results carry
a usage summary with the actual cost and the cost repriced at Standard prices (Contributor
calls priced as Spark). The benchmark reports tokens, costs, latency and cache hit rate per stage
(`investigation`, `escalation`), and the golden runner per question type.

## Consequences

- Costs are bounded by construction (caps checked before the call), at the price of refusing
  some calls a cache hit would have made cheap.
- Repeated investigations of an unchanged incident are free; the cache key is conservative
  (any fact, prompt or config change re-runs the model).
- Truncated tool results can hide evidence; the explicit marker and the "narrow the query" note
  make that visible to the model and in the stored tool log.
- The Standard repricing of economy runs prices escalations at Spark, not Wonder (ADR 0011);
  the production-routing golden run gives the realistic figure.
