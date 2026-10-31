# Launch readiness review

Status: v1.1 · Owner: Kevin Masra · Last updated: 2026-10-31

This is the review a product goes through before real merchants connect real stores. Each item is
marked **Ready** (built and tested), **Partial** (built, with a known gap) or **Planned** (not built
yet, with the task that delivers it). Numbers come from the committed reports in `bench/reports/`.

Launch model: **built to scale, launched small.** Private beta from a waitlist, then 10 design
partners, then paid plans. The architecture supports thousands of stores; the first users are few
and followed closely.

---

## 1. Go / no-go for the private beta

| Gate | Status | Evidence |
| --- | --- | --- |
| No invented numbers in any output | Ready | Verifier on 100% of outputs; 0 violations in every run |
| No action outside policy, no duplicate execution | Ready | Action red team: 8 of 8 cases pass |
| Prompt injection from store data cannot cause harm | Ready | Real-model red team: 0 unsafe of 10; scripted: 0 of 14 |
| Tenant isolation | Ready | Row-level security, tested on every tenant table |
| Real store data never used for model training | Ready | Contributor mode refused in code for non-synthetic stores; Standard mode only |
| Store data deletion and export on request | Ready | `GET /stores/{id}/export`, `DELETE /stores/{id}` (ADR 0021): after a deletion through the API, a test finds no row of the store in any of the 30+ tenant tables nor in the access tables, and the deletion recorded |
| Owner authentication | Ready | Email sign-in links (single use, 15 minutes), HTTP-only session cookies with CSRF, per-store API tokens (ADR 0020); every store route tested with another store's credentials (404) and with none (401) |
| Alert precision on healthy stores | Ready | 1 false alert in 30 healthy hold-out stores |
| Root-cause accuracy | Partial | 70% top-1 on unseen stores (hold-out); see section 8 |
| Outcome intervals hold the truth | Ready | Calibrated P10-P90 holds the true effect 82% of the time on 70 fresh stores (target 80%); widening fitted on dev and frozen first (ADR 0018); 10% abstain |
| Live execution on Meta | Partial | Built against Meta's published API; live sandbox run pending credentials |
| Cost per store under control | Ready | Budget guard on every call; see section 7 |

## 2. Security

| Control | Status |
| --- | --- |
| LLMs have no write tools; writes only in the executor, behind the policy engine | Ready |
| Database guard refuses writes from the agent's connection except new facts | Ready |
| Store-provided text passed as escaped data, never in system prompts | Ready |
| Merchant names escaped per channel (HTML, plain text) | Ready |
| Email approval links HMAC-signed, single use, 24 h expiry; above cap only a confirmation page | Ready |
| Secrets only in environment; gitleaks in CI; cassettes scanned for keys | Ready |
| Dependency audit (pip-audit) in CI | Ready |
| `SECURITY DEFINER` function hardened (fixed search_path, no free-form arguments, typed parameters only, no PUBLIC grant) | Ready |
| API authentication (sessions with CSRF, per-store API tokens), rate limits per address and per store, security headers, problem details with request ids (ADR 0020) | Ready |
| Every store route scoped to the caller's stores; another store is answered 404, tested route by route | Ready |
| Access tokens to Meta and Shopify encrypted at rest: AES-256-GCM envelope, a data key per token, the master key from the environment, bound to the store and provider (ADR 0021) | Ready |

## 3. Privacy and data protection

- **Data minimisation.** Models receive facts and summaries, never raw customer records.
  No customer names, emails or addresses are needed by the product.
- **No training on merchant data.** Real stores use Standard mode only; requests are sent with
  `store: false`.
- **Retention.** Raw store data kept while the store is connected; facts, decisions and the audit
  log kept for the life of the account; model traces kept 30 days (a daily job deletes older
  step traces, and expired sign-in links and sessions; ADR 0021). Database backups follow the
  hosting provider's retention, to be kept within the 30-day target below.
- **Rights.** Export and deletion of all of a store's data on request, with the deletion itself
  recorded outside the store's data (`GET /stores/{id}/export`, `DELETE /stores/{id}`; ADR 0021).
  Both run at once; target: completed within 30 days of the request, backups included.
- **Sub-processors.** Meta Model API (model inference), hosting provider, transactional email
  provider. Listed publicly before the beta.
- **GDPR.** Required before onboarding any store in the European Union: a data processing
  agreement, the sub-processor list and the rights process above.

## 4. Reliability objectives

| Objective | Target |
| --- | --- |
| Time from data arrival to alert | p95 under 5 minutes |
| Scheduled briefings delivered on time | 99% |
| API availability | 99.5% monthly |
| Action execution after approval | p95 under 2 minutes; never twice |
| Model provider outage | No false alert, no action; briefings sent from facts only (deterministic fallback) |

Mechanisms in place: transactional outbox, idempotency enforced by the database, retries with
backoff and jitter, circuit breaker per provider, global and per-store kill switches, structured
logs and traces for every model call and agent step.

## 5. Safety of actions

- Policy engine evaluated before every action, first refusal wins, every evaluation audited:
  kill switches, executable kinds, autonomy level, ±30% budget cap, one change per campaign per
  24 hours, reversibility.
- Autonomy starts at "recommend": every action needs the owner's approval. The trust ledger can only
  propose a promotion, after 10 measured outcomes with at least 75% inside the predicted range and
  no rollback.
- Every executed action has a rollback (pause ↔ resume, budget restored).
- Decisions follow a state machine enforced by a database trigger; all 57 illegal transitions tested.

## 6. Incident response

| Severity | Example | First action |
| --- | --- | --- |
| SEV1 | An action executed outside policy, or data visible to another store | Global kill switch; notify affected owners within 24 h |
| SEV2 | Wrong alerts at scale, model provider down, executor failing | Pause alerts or actions for affected stores; deterministic fallback |
| SEV3 | One store's data stale, one wrong answer reported | Fix, reply to the owner, add a regression test |

Process: detect (alerts on error rates, spend, latency) → mitigate (kill switch first) → communicate
→ fix → blameless postmortem within 5 working days, with a regression test added to the benchmark
or red-team suite.

## 7. Unit economics

<!-- unit-economics:begin -->
Generated by `uv run python -m bench.unit_economics` from measured costs at Standard prices (`bench/reports/unit-economics.md`): an investigation USD 0.0905 on average (USD 0.3286 at most, 51 investigations), an Ask answer USD 0.0280 (80 answers), a daily brief USD 0.0069, a weekly report USD 0.0136, a monthly review USD 0.0138.

Per store and month: 26 daily briefs, 4 weekly reports, 1 monthly review, email USD 0.05, payment processing 3% + USD 0.30; infrastructure is an estimate for a shared deployment.

| Profile | Investigations | Questions | Model cost | Infra | Email | Payment | Total cost | Price | Gross margin |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Typical store | 10 | 30 | USD 1.99 | USD 2.00 | USD 0.05 | USD 1.77 | USD 5.81 | USD 49.00 / month | 88% |
| Busy store | 40 | 150 | USD 8.06 | USD 4.00 | USD 0.05 | USD 4.77 | USD 16.88 | USD 149.00 / month | 89% |
| Busy, every investigation at max cost | 40 | 150 | USD 17.59 | USD 4.00 | USD 0.05 | USD 4.77 | USD 26.41 | USD 149.00 / month | 82% |
<!-- unit-economics:end -->

Prices are working hypotheses to validate with design partners. Gross margin stays above 80% even
in the worst observed case, because the expensive model is used only on ambiguous incidents and
most context is served from the prompt cache. Briefing costs were estimates before Task 5; every
figure above is now measured, and total cost includes payment processing.

## 8. Known limitations (published, not hidden)

- **Root-cause accuracy** is 70% top-1 and 75% top-3 on unseen stores; the detectors reach 86% on
  the scenarios they were tuned on. The investigator agent does not yet improve the ranking.
- **Golden questions** pass at 73–83% depending on routing and run, against a 90% target (six
  economy runs before and after citations were attached in code: 77.8% and 78.9% on average,
  `bench/reports/citation-attach.md`). Most misses are answers that do not cite the fact of the
  metric the question asks about.
- **Twin calibration** covers 74% of outcomes on unseen stores (target 75–85%); pauses are the
  weakest at 63%.
- **Outcome measurement** (`bench/reports/outcome-validation-fresh.md`): on 70 fresh stores the
  calibrated P10-P90 holds the true effect 82% of the time (target 80%), but only because of a
  widening fitted on dev: the raw intervals held it 74% of the time there and 66% on dev. 10% of
  outcomes abstain on a weak pre-period fit; the 0.5 threshold withholds worse estimates on the
  fresh stores and no worse ones on dev, so it stays under review. Validated on simulated
  stores only, with a 7-day window; real stores will be noisier.
- **Benchmark realism.** The store generator uses the same ad-response curve shape as the twin, which
  makes twin results optimistic; price effects cannot be calibrated because simulated demand ignores
  price.
- **Data days.** Facts and briefings count days as UTC calendar days, not days in the store's
  time zone: for a store far from UTC, "yesterday" in a briefing is the UTC day, which can
  differ by a few hours from the owner's local day. Schedules do use the store's time zone.
- **Scope.** One currency per store, Meta Ads only, English only.

## 9. Launch plan

1. **Private beta (waitlist).** Invite stores in small batches; autonomy fixed at "recommend".
2. **Design partners (10 stores).** Weekly review of every alert, answer and decision with the owner;
   every miss becomes a benchmark scenario.
3. **Paid plans.** When design partners confirm measurable value: a profit gain or a loss avoided
   larger than the price, measured by the product's own outcome measurement.
