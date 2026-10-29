# ADR 0009: LLM provider, cost guards and record/replay

- Status: accepted
- Date: 2026-10-29

## Context

The investigator and Ask call Meta models (Muse Spark 1.3, Muse Wonder 1.0) through the Meta
Model API's Responses API. Calls cost money, fail transiently, may change format, and must
never carry real store data to a mode that trains on it. Tests and CI must not need a key or a
network, and must still exercise the real client code.

## Decision

**One interface.** `LLMProvider.generate(LLMRequest) -> LLMResult`; the implementation
`MetaResponsesProvider` uses the OpenAI SDK (`base_url=https://api.meta.ai/v1`, the key from
`MODEL_API_KEY` passed explicitly, SDK retries off) and follows the Responses API documentation
as checked on 2026-10-28:

| Concern | Choice |
| --- | --- |
| Tools | flat `{"type": "function", name, description, parameters, strict: true}`; `tool_choice: "auto"` (the only supported value) |
| Structured output | `text.format = {type: json_schema, name, schema, strict: true}`; schemas generated from Pydantic and rewritten to the strict subset (refs inlined, all properties required, `additionalProperties: false`, recursive and free-form maps rejected); the answer is validated again with Pydantic |
| Reasoning | effort always explicit (default `low`; omitting it was observed to mean `high`); `none` is never sent |
| State | `store: false` and `include: ["reasoning.encrypted_content"]`: the conversation is replayed statelessly (reasoning and function-call items sent back), so Meta does not keep store data |
| Prompt caching | automatic prefix caching; every request carries a stable `prompt_cache_key` (default `model:purpose:prompt_version`); system prompt first, variable content last |
| Responses | the raw JSON is validated against the documented shape (`object`, `status`, `output` items, `usage` with cached and reasoning tokens): a difference raises `ResponseFormatError`. `incomplete` and `failed` statuses are errors; refusals are surfaced |

**Data policy.** `muse-spark-1.3-contributor` lets Meta train on prompts and responses: it is
refused unless `DataOrigin.SYNTHETIC`, which is read from `stores.synthetic` (set only by the
benchmark generator), never asserted by a caller. Record mode also refuses real store data,
because cassettes are committed.

**Cost.** A versioned price table (`prices_v1.toml`, USD per 1M tokens, verified on 2026-10-28
against the pricing page) gives the exact cost of each call: uncached input, cached input and
output (reasoning tokens are billed as output and included in `output_tokens`, as observed live).

**Guards.**

- Budget: before each call, its worst case (request bytes as input tokens, all
  `max_output_tokens` used) is reserved against the per-run, daily and optional total caps; the
  call is refused when a cap could be exceeded; the reservation is settled to the actual cost.
  Ledger: in memory, or a JSON-lines file under a lock file shared by processes.
- Retries: 429, 500, 503, failed-with-server-error, timeouts and connection errors, with
  exponential backoff (0.5 s, doubling, capped at 8 s) plus up to 1 s of jitter, honouring
  `Retry-After` up to 60 s, 4 attempts. 400/401/402/403/404/413 and 504 are not retried.
- Circuit breaker per provider: opens after 5 consecutive provider-side failures, one trial call
  after 30 s.
- Telemetry: one OpenTelemetry span per call with model, data mode, transport, purpose, run,
  prompt version hash, tokens (input, cached, output, reasoning), cost, latency, attempts and
  outcome; one structured log line.

**Record / replay.** The transport is chosen by `LLM_MODE`: `live`, `record` (live, then write
the exchange) or `replay` (the default). A cassette is keyed by the SHA-256 of the normalised
request (method, path, JSON body; headers, hence the key, are never stored) and lives under
`backend/tests/cassettes/recorded/` (hand-written ones, marked `"synthetic": true`, would go
under `synthetic/`; the first ones were replaced by real recordings on 2026-10-29). Replay
prefers recorded cassettes and raises on a miss. A test fails if a cassette holds the API key,
an Authorization or Bearer header, a key-like token, a cookie or a private key, or keeps
headers beyond content type and rate-limit counts.
CI sets `LLM_MODE=replay` and has no key; a test fixture also disables the real HTTP transport.
Unit tests use a scripted fake transport that answers in the documented format (tool calls,
structured output, refusals, errors, rate limits, timeouts).

`scripts/smoke_live.py` (`make smoke-live`) runs, per model, a tool call then a structured
output, prints tokens and cost, and fails loudly on any difference; `--mode record` writes the
real cassettes.

## Consequences

- The real SDK and parsing code run in every test, without a network.
- A request change (prompt, schema, encoding) changes cassette keys: replay fails until the
  cassettes are re-recorded (`scripts/smoke_live.py --mode record`), which is the point.
- The budget bound is conservative (bytes overestimate tokens several times): a per-run cap
  close to the expected cost can refuse calls that would have fitted.
- Cache hits depend on routing: even with a key, a follow-up turn sometimes misses.

## Live verification (2026-10-29)

Minimal calls on the three models, $0.094 in total (exact, from the spend ledger).

| Item | Status | Finding |
| --- | --- | --- |
| Response shape for tool calls and structured output | verified | the smoke conversation passes on all three models; strict parsing found no difference |
| Strict schemas | verified | the nine tool schemas and the answer contract in one request are accepted by all three models, which return a parsed answer |
| Tools and structured output in one request | verified | same calls |
| Stateless reasoning replay (`store: false`) | verified | every reasoning item carries `encrypted_content`; follow-up turns that replay it complete |
| Reasoning efforts | fixed | the Contributor model accepts `minimal` to `max` (the docs say `max` is not available) and rejects `none`; Spark accepts `max`, Wonder `minimal` |
| Error bodies | verified | 400 (`tool_choice: "required"`), 404 `model_not_found`, 401 `invalid_api_key` have the documented `error` object and map to the right errors |
| Rate-limit headers | verified | `x-ratelimit-{limit,remaining}-{requests,tokens}` on success; an `x-request-id` header is now recorded on results, spans and errors |
| Prompt caching | fixed | caching works on all three models (identical requests hit; minimum length is not an issue at ~600 tokens). Follow-up turns without a key reused the prefix 4/8 times (Contributor) and 1/3 (Wonder); with a stable key 7/8 and 2/3. Our requests sent no key: now they always do. Recorded run: 625, 625 and 500 cached tokens on turn 2 |
| Cost | verified | computed costs match the price table; reasoning tokens are part of `output_tokens` |
| Real cassettes | verified | six recorded, scanned for secrets, replayed in CI |
| `Retry-After` on 429 / 503, 504 behaviour | pending | not triggered on purpose (it would mean loading the API) |
| Reconciliation with the Meta invoice | pending | needs the billing dashboard |
| A real model under the red-team attacks | pending | Part B (investigator runs) |
