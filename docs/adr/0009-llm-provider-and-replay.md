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
| Reasoning | effort always explicit (default `low`; omitting it was observed to mean `high`); `max` refused for the Contributor model |
| State | `store: false` and `include: ["reasoning.encrypted_content"]`: the conversation is replayed statelessly (reasoning and function-call items sent back), so Meta does not keep store data |
| Prompt caching | automatic prefix caching; a stable `prompt_cache_key` per prompt version; system prompt first, variable content last |
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
`backend/tests/cassettes/recorded/` or, hand-written in the documented format and marked
`"synthetic": true`, under `synthetic/`. Replay prefers recorded cassettes and raises on a miss.
CI sets `LLM_MODE=replay` and has no key; a test fixture also disables the real HTTP transport.
Unit tests use a scripted fake transport that answers in the documented format (tool calls,
structured output, refusals, errors, rate limits, timeouts).

`scripts/smoke_live.py` (`make smoke-live`) runs, per model, a tool call then a structured
output, prints tokens and cost, and fails loudly on any difference; `--mode record` writes the
real cassettes.

## Consequences

- The real SDK and parsing code run in every test, without a network.
- A request change (prompt, schema, encoding) changes cassette keys: replay fails until the
  cassettes are re-recorded (or the synthetic ones rebuilt), which is the point.
- The budget bound is conservative (bytes overestimate tokens several times): a per-run cap
  close to the expected cost can refuse calls that would have fitted.
- Pending live verification: the response shapes and usage fields beyond the single observed
  call, tool calling and strict structured output on each model, stateless replay of encrypted
  reasoning with `store: false`, Retry-After and rate-limit headers, prompt caching hits, and
  the Contributor model's accepted reasoning efforts.
