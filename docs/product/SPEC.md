# Product specification

Status: v1.4 · Owner: Kevin Masra · Last updated: 2026-10-31
(v1.1: alert severity scales with store size, section 6.
v1.2: north star, agent as auditor (section 15), token and cost management (section 16).
v1.3: goals, feasibility and plans (section 17).
v1.4: goals beyond 90 days (section 17.2).)

This document defines what the product delivers to a store owner, the exact shape of every output,
and how quality is measured. Every engineering task must move the evaluations defined in section 12.
Each feature is tagged with its phase: **[H]** hackathon must-have, **[H+]** hackathon stretch,
**[L]** later.

---

## 0. North star

### Long-term goal

Become the profit analyst of every online store that cannot afford one: the system that watches the
business, finds where money is lost or could be made, proves it, acts with the owner's control and
learns from measured results. Then extend it to every data source and sector where a wrong decision
costs money.

### Hackathon goal (definition of done, November 4)

In a three-minute video, a judge watches a store that is losing money without knowing it. The
system detects it on its own, proves the cause number by number, simulates the options, the owner
approves, the action really executes on Meta, and the result is measured. Then the judge sees why
it can be trusted: a published benchmark, zero invented numbers, zero dangerous actions.

Done means every item below is true and shown:

- [ ] The full loop runs end to end on a demo store: detect → investigate → alert → options with
      ranges → approval → real execution on a Meta test ad account → journal → measured outcome.
- [ ] The owner can ask questions (including "what can I do?" and "I want to do X") and every answer
      follows the answer contract.
- [ ] Daily brief and weekly report are generated from facts only.
- [ ] Every number in every output is clickable down to its formula and source rows.
- [ ] The benchmark report is published in the repository, with the deterministic baseline and the
      agent side by side, on a hold-out suite never used for tuning.
- [ ] The golden question set passes at the target rate.
- [ ] The red-team suite shows zero unsafe outcomes with a real model.
- [ ] Every target in section 12 is met, or the miss is reported with its reason.
- [ ] The repository is public, CI is green, and a judge can run it with one documented command.
- [ ] The web platform shows the journal, the evidence and the decisions, built on the API.
- [ ] The owner can set a goal and get a computed feasibility, a plan with weekly milestones, and
      weekly tracking; the backtest of forecasts and probabilities is published.

---

## 1. Purpose and principles

**Promise.** An AI profit analyst for e-commerce stores. It finds where the store loses or could
make money, proves it with verifiable numbers, acts with the owner's approval, and measures what each
decision actually earned.

**Principles.**
1. **Money first.** Every alert, insight and recommendation is expressed as an impact on profit.
2. **Proof over persuasion.** Every number is a fact with a formula and lineage. Estimates are ranges.
3. **Signal over noise.** Nothing reaches the owner unless it is both statistically real and
   economically material.
4. **The product comes to the owner.** Proactive by default; the owner never has to know which
   question to ask.
5. **Control stays with the owner.** Actions are approved, capped, reversible when possible and logged.
6. **Honest limits.** When data is missing or evidence is weak, the product says so.
7. **Two keys.** The code checks the agent (no invented number, entity or action); the agent
   audits the code (robustness, consistency, method). Neither can override the other.

## 2. Users and jobs to be done

**Primary user: the owner-operator** of an online store (Shopify first) spending on Meta ads, with no
analyst or finance team.

| Job | The owner wants to… |
| --- | --- |
| Stay informed | know in 30 seconds whether the business is healthy and what needs attention |
| Stop losses | find and stop what loses money before it grows |
| Grow profit | know which actions would earn the most, with their risk |
| Decide safely | check an idea ("I want to run a 20% promo") before spending money |
| Trust the numbers | see where every number comes from |
| Learn | know which past decisions worked |

Secondary users **[L]**: marketing or operations manager, accountant (read-only).

## 3. Surfaces and channels

| Surface | What it is | Phase |
| --- | --- | --- |
| Briefings | Scheduled daily, weekly and monthly reports | [H] daily + weekly, [H+] monthly |
| Alerts | Real-time notification of a material incident | [H] |
| Ask | Natural-language questions answered from the store's own data | [H] |
| Decisions | Options, approval, execution, outcome | [H] |
| Journal | Chronological record of incidents, decisions, actions and outcomes | [H] |
| Settings | Cadence, channels, thresholds, autonomy, connections | [H] API, UI later |

Channels: web platform **[H]**, email **[H]**, WhatsApp **[H+]**, SMS and Slack **[L]**.
All channels share one decision object and one journal.

## 4. Store configuration

| Setting | Default | Notes |
| --- | --- | --- |
| Timezone | Store's Shopify timezone | All schedules in local time; storage in UTC |
| Currency | Store currency | One currency per store **[H]**; FX **[L]** |
| Daily brief | 08:00, Monday–Saturday | Can be disabled |
| Weekly report | Monday 08:00 | Covers the previous Monday–Sunday |
| Monthly review | 1st of month, 08:00 | **[H+]** |
| Alert channels | Web + email | WhatsApp opt-in **[H+]** |
| Quiet hours | 21:00–07:00 | Only `critical` alerts break quiet hours |
| Alert budget | Max 3 non-critical alerts per day | Overflow goes to the next briefing |
| Materiality (absolute) | 100 in store currency per month | Minimum expected monthly profit impact to alert |
| Materiality (relative) | 3% of trailing-30-day contribution margin | An alert needs both absolute and relative materiality |
| Detail level | `standard` | `brief` · `standard` · `expert` (adds formulas and methods inline) |
| Autonomy | Level 2 (recommend, owner approves) for every action type | See section 7 |
| Spending caps | Budget change ≤ 30% per action, ≤ 1 change per campaign per 24 h | Hard limits in the policy engine |
| Language | English | French **[L]** |

## 5. Briefings

All briefings follow the same rules: the most important item first, at most three action items,
every number a fact reference, every estimate a range, and a link to the evidence for each item.

### 5.1 Daily brief [H]

Target reading time: 30 seconds.

1. **Health line.** One sentence: profit yesterday and over the last 7 days versus the previous 7 days.
2. **Money at stake.** The total estimated monthly profit impact of open incidents, as a range.
3. **Top items (≤ 3).** For each: what happened, the impact, the recommended action, one button.
4. **Pending decisions.** Decisions awaiting approval, oldest first.
5. **Data notice.** Only if a source is stale, incomplete or inconsistent.

If nothing is material: "Nothing needs your attention today" plus the health line. No filler.

### 5.2 Weekly report [H]

Target reading time: 3 minutes.

1. **Summary.** Net profit, contribution margin, revenue, ad spend: this week vs last week and vs the
   4-week average.
2. **Profit bridge.** Shapley attribution of the change in net profit by driver (volume, mix, price,
   unit cost, fees, refunds, ad spend, fixed costs), with drivers inside the noise band marked
   "not significant".
3. **Campaigns.** Per campaign: spend, attributed contribution, campaign profit, POAS, trend,
   attribution ratio. Sorted by campaign profit, worst first.
4. **Products.** Top 5 profit gainers and top 5 decliners, with the driver behind each.
5. **Inventory.** Products whose cover is below supplier lead time, especially those being advertised.
6. **Decisions and outcomes.** Decisions taken, actions executed, and measured outcomes with intervals.
7. **Opportunities.** Up to three ranked opportunities (section 9).
8. **Watchlist.** Signals not yet material, to check next week.

### 5.3 Monthly review [H+]

Weekly content at month scale, plus: unit economics per product, fixed-cost trend, trust ledger
(prediction accuracy per action type and autonomy proposals), and a review of every decision with
predicted vs measured impact.

## 6. Alerts [H]

**Trigger.** An incident becomes an alert only if all are true:
1. Statistically real: detector thresholds met with persistence and multiple-testing correction.
2. Economically material: expected monthly profit impact meets both materiality thresholds.
3. Not a duplicate: no open alert covers the same incident.

**Severity.**

| Severity | Rule | Delivery |
| --- | --- | --- |
| `critical` | P50 monthly loss ≥ 10% of trailing-30-day contribution margin, or money is actively being spent on an impossible sale (e.g. ads on a product out of stock) | Immediately, breaks quiet hours |
| `high` | P50 monthly loss ≥ 5% of trailing-30-day contribution margin | Immediately, within the alert budget |
| `normal` | Material (both materiality thresholds met) | Within the alert budget, else next briefing |
| Data quality | Tracking break, stale source, reconciliation gap | Separate category, never presented as a profit problem |

Severity scales with store size: the relative tiers apply on top of the absolute materiality floor,
so a large store is not flooded with `critical` alerts for amounts that are small for it.

**Content (always these six parts).** What was detected · why it matters (impact range) ·
evidence (facts, clickable) · what is still uncertain · options with estimated impact ·
recommended next step.

## 7. Decisions and actions

**Decision object.** Incident or question, options (2–3), each with predicted impact (P10/P50/P90),
risks, reversibility and invalidation conditions; recommended option; status
(`proposed → approved | rejected | expired → executing → executed | failed → measured`).
A decision transitions exactly once, whatever the channel.

**Action catalogue.**

| Action | Mode | Phase |
| --- | --- | --- |
| Pause a campaign | Execute via Meta Marketing API | [H] |
| Change a campaign's daily budget | Execute, capped (±30%) | [H] |
| Resume a campaign | Execute (rollback of pause) | [H] |
| Reorder a product | Prepare a purchase suggestion only | [H] |
| Change a price | Prepare only | [H+] |
| New ad creative variant | Prepare with Muse Image + SAM, owner approves | [H+] |

**Autonomy levels.** 1 observe · 2 recommend (owner approves) · 3 execute under caps · 4 manage a
scope. Promotion is proposed by the trust ledger after enough accurate predictions; any serious error
demotes automatically.

**Outcome measurement.** After the observation window (default 7 days), the causal module estimates
the effect with an interval, or abstains when the pre-period fit is too weak.

## 8. Ask [H]

The owner can ask anything about their store. Every answer follows the **answer contract**:

| Field | Required | Content |
| --- | --- | --- |
| `answer` | yes | One or two sentences that answer the question directly |
| `evidence` | yes | Fact references supporting the answer |
| `reasoning` | when non-trivial | How the evidence leads to the answer |
| `alternatives` | for why / what-if / evaluate | Other explanations or options considered |
| `uncertainty` | yes | What is unknown, missing or estimated |
| `recommendation` | when actionable | The next step, possibly a decision to approve |
| `would_change_my_mind` | for recommendations | What evidence would invalidate it |

**Question types.**

| Type | Example | Expected shape |
| --- | --- | --- |
| Lookup | "What was my profit last week?" | Fact + comparison |
| Explain a number | "How is campaign profit computed?" | Formula + inputs + lineage |
| Diagnose | "Why is my profit down?" | Profit bridge + ranked causes + evidence |
| Improve | "What can I do to make more money?" | Ranked opportunities: impact range, effort, risk, reversibility |
| Evaluate an intent | "I want to run a 20% discount on product X" | Simulation, verdict (`go` · `adjust` · `avoid`), better alternative if any |
| What-if | "What if I cut Meta spend by 30%?" | Simulated impact range + main assumption |
| Review | "Did pausing campaign Y work?" | Measured outcome vs prediction, or abstention |
| Data question | "Can I trust my Meta numbers?" | Attribution ratio, reconciliation, caveats |
| Goal | "I want 60,000 in net profit by the end of March" | Restated goal to confirm, then feasibility, gap and plan (section 17) |
| Out of scope | "Should I hire someone?" | Honest scope statement + what the product can say |

## 9. Opportunities [H] internal, [L] market

Internal opportunities found in the store's own data, each with impact range, effort, risk and a
test plan:
- Reallocate budget from negative-profit to positive-profit campaigns.
- Under-funded profitable campaign (spending below its estimated optimum).
- High-margin product with strong organic sales and little ad support.
- Price headroom where demand is weakly price-sensitive (estimate with wide range).
- Refund driver worth fixing (product with abnormal refund rate).

Market opportunities (trends, regions, new products) **[L]**, always proposed as small capped tests.

## 10. Expert lenses

Each output is designed to satisfy the standard of these roles.

| Lens | What it guarantees | Concrete outputs |
| --- | --- | --- |
| Data engineer | Data is fresh, complete, consistent and traceable | Freshness per source, reconciliation gaps, lineage on every fact, data-quality incidents |
| Data analyst | The right metrics, compared the right way | KPI definitions, period comparisons, segment views, trend charts |
| Data scientist | Claims match the strength of the evidence | Significance + materiality gating, noise bands, intervals, causal outcome measurement, abstention |
| E-commerce operator | Recommendations are concrete and doable today | Playbooks: pause, reallocate, reorder, reprice, fix product page or quality |
| Finance | Profit is real, not revenue | Contribution margin, POAS, unit economics, fixed costs |
| Marketing | Ad numbers are read critically | Attribution ratio, over-attribution warnings, incrementality checks |
| Security and risk | Nothing harmful can happen | Policy engine, caps, approvals, kill switch, audit log, injection defences |

## 11. Golden examples (illustrative values)

Values below illustrate the format. In production every number is a rendered fact.

### 11.1 Daily brief

> **Tuesday, Oct 27 — 1 item needs you.**
> Profit last 7 days: $4,120, down 18% vs the previous 7 days.
> Money at stake: about $1,100–1,500 per month.
>
> **1. Campaign "Summer Sneakers" is losing money (high).**
> It spent $1,240 in 14 days and its attributed contribution was $610: a campaign profit of −$630.
> The cost per purchase rose steadily since Oct 9. [Evidence]
> Recommended: reduce its daily budget by 30%, or pause it. [Review options]
>
> Pending: none · Data: all sources up to date.

### 11.2 Ask — evaluate an intent

> **You:** I want to run a 20% discount on the Trail Jacket for two weeks.
>
> **Answer:** Probably not worth it as planned: at 20% off, each sale would earn $3 instead of $21,
> so you would need about 7 times more sales just to stay even. Expected impact over two weeks:
> −$900 to +$150, most likely −$420. [Evidence]
> **Better option:** 10% off for returning customers only: −$80 to +$260, most likely +$90.
> **Uncertain:** we have never seen this product discounted, so price sensitivity is estimated
> with a wide range.
> **Would change my mind:** clearing excess stock is the real goal (current cover: 96 days).

### 11.3 Alert — data quality

> **Data issue, not a profit issue.** Meta stopped reporting purchases for "Retargeting" on Oct 24,
> while your real orders for its products are unchanged. Your reported ROAS for this campaign is
> unreliable until tracking is fixed. Likely cause: pixel or conversion API change.
> No budget action recommended until tracking is restored.

## 12. Quality bar and evaluations

| Metric | Target | Measured by |
| --- | --- | --- |
| Unverified numbers in any output | 0 | Verifier on 100% of outputs |
| Correct root cause, top-1 | ≥ 85% | Benchmark (`make eval`) |
| Correct root cause, top-3 | ≥ 95% | Benchmark |
| False profit alerts on healthy stores | ≤ 1 in 30 | Benchmark, ≥ 30 healthy stores |
| Tracking breaks classified as data quality | 100% | Benchmark |
| Interval coverage of P10–P90 | 75–85% | Simulation calibration |
| Dangerous actions under attack suite | 0 | Red-team suite |
| Duplicate executions | 0 | Idempotency tests |
| Golden questions passing | ≥ 90% | `bench/golden/questions.yaml` |
| Time from data arrival to alert | < 5 min | End-to-end test |
| Model cost per daily brief | < $0.05 | Cost accounting |
| Model cost per investigation | < $0.50 | Cost accounting |
| Investigations with a robustness check | 100% | Audit findings in each investigation |
| Confident errors (wrong top-1 with `high` confidence) | ≤ 5% | Benchmark |
| Accuracy of `high`-confidence conclusions | ≥ 90% | Benchmark, per confidence level |
| Tokens and cost per stage | Reported | Benchmark report |

**Golden question set.** `bench/golden/questions.yaml` lists questions tied to benchmark scenarios
with machine-checkable expectations: required metrics, required entities, expected verdict or action
family, and forbidden behaviours. A question passes only if every check passes and the verifier
reports zero violations.

## 13. Scope by phase

**Hackathon must-have [H].** Shopify-shaped data + Meta Ads; facts and verifier; detectors with
significance and materiality; incidents; Shapley profit bridge; investigator agent (Muse Spark,
Muse Wonder for hard cases); simulation of options; decision object; policy engine; outbox executor
with pause / budget / resume on Meta; daily brief, weekly report, alerts and Ask through the API;
email channel; journal; benchmark and golden questions; web platform built on the API; goals,
feasibility, plans and weekly tracking (section 17).

**Hackathon stretch [H+].** Market context for goals through search grounding; WhatsApp alerts and approvals; voice questions (Muse Voice Transcribe);
monthly review; ad creative variants (Muse Image + SAM); Muse Spark Open via Baseten for
high-volume work; local privacy mode.

**Later [L].** Google Ads and TikTok Ads; customer emails and social comments as signals; market
opportunities; FX; multiple users and roles; SMS and Slack; French.

## 14. Non-goals

- Not a general assistant: it answers questions about the store's profit and operations only.
- Not a dashboard to explore freely: it decides what deserves attention.
- Not a customer-support or social-media publishing tool.
- Never presents platform-reported attribution as truth.
- Never executes an action that the policy engine has not approved.

## 15. Agent as auditor [H]

The deterministic pipeline checks the agent; the agent also cross-examines the pipeline.

**What the agent audits, with read-only tools:**

| Audit | Question | Tool |
| --- | --- | --- |
| Robustness | Does the conclusion survive other reasonable windows and baselines? | `run_sensitivity` |
| Consistency | Do product totals add up to the store? Do platform-attributed sales match real orders? | `check_reconciliation` |
| Method | Is the baseline contaminated by the fault? Is the data complete? Is the method suited to the case? | `get_method` |

**Output.** Every investigation contains `audit_findings`, each with a kind
(`unstable_conclusion`, `window_contamination`, `reconciliation_gap`, `data_gap`, `weak_evidence`,
`method_mismatch`), its evidence (fact ids), its effect and the check to run next.

**Rules.**
- Stability is computed by code, not judged by the model. If the conclusion is unstable under
  sensitivity, confidence is capped at `medium` and the answer carries `low_evidence`, whatever the
  model says.
- The agent may challenge a result, request a recomputation through tools and lower confidence.
  It never changes a formula, a threshold or a setting at runtime.
- Proposals to improve detectors are written to an offline report and applied only after human
  review and a new hold-out evaluation.

## 16. Token and cost management [H]

| Lever | Rule |
| --- | --- |
| Model routing | Spark Contributor for classification on synthetic stores; Spark by default; Wonder only for ambiguous incidents. Real store data always in Standard mode. |
| Reasoning effort | Set per stage: low for classification and lookups, medium for investigations, high only on Wonder escalations. |
| Output limits | A maximum output length per stage. |
| Prompt caching | Stable prefix first (system prompt, tool schemas), variable content last; a stable cache key per prompt version and purpose. Budgets assume no cache hit. |
| Compact context | Tools return facts and summaries, never raw daily series; each tool result has a size limit. |
| Budgets | Per investigation: maximum tool calls and cumulative input tokens, with a clean stop and a partial answer. Per run and per day: hard spend caps. |
| No duplicate work | Identical tool calls within an investigation are memoised; an investigation whose facts, prompt version and model are unchanged is served from cache. |
| Measurement | Tokens (input, cached, output, reasoning), cost and latency per stage, reported in every benchmark run, with an estimate of production cost at Standard prices. |

## 17. Goals, feasibility and plans [H]

The owner sets a goal; the product says whether it is reachable, proves it, proposes a plan, and
checks progress every week. The promise: **"It tells you whether your goal is realistic, proves it,
and checks every week."**

### 17.1 Goal

- A goal has a metric (`net_profit`, `contribution_margin`, or `revenue`), a target, a deadline
  (month, quarter or up to six months) and a scope (store first).
- The product restates the goal in plain words and asks the owner to confirm before any analysis.
  An ambiguous goal gets a question back, never a guess.
- A revenue goal is accepted, but the answer always shows its effect on profit; if the plan would
  grow revenue while lowering profit, it says so first.

### 17.2 Feasibility (computed by code)

1. **Baseline trajectory.** Forecast of the metric to the deadline if nothing changes: trend, weekly
   seasonality and uncertainty that widens with the horizon, as P10/P50/P90 paths.
2. **Probability of reaching the target** = the share of simulated paths that reach it. It is an
   `estimate` fact, never written by a model.
3. **Verdict** from that probability: `likely` (≥ 70%), `possible` (40–70%), `stretch` (15–40%),
   `unlikely` (< 15%), shown with the probability range and its assumptions.
4. **Gap** = target minus the baseline P50.
5. **Honesty rules.** When the horizon is longer than the store's history, or the backtest calibration
   for that horizon is weak, the answer carries `low_evidence` and says why. Probabilities are never
   presented as promises.
6. **Beyond 90 days.** The backtests found probabilities past 90 days overconfident, so a goal with a
   longer horizon shows no point probability: it shows the verdict band and the probability
   interval, with `low_evidence` and the reason. Such a goal is split into quarterly checkpoints
   (every 90 days to the deadline, each with its forecast range); the plan is detailed and
   simulated for the first 90 days only, and the forecast is redone every month.

### 17.3 Plan

- Built from a **library of proven levers**, each with its mechanism, the facts that make it
  applicable, and an effect simulated by the twin:
  reallocate budget from negative-profit to positive-profit campaigns; scale profitable campaigns
  within caps; prevent stockouts on products that sell; cut spend on products that cannot be sold;
  shift ad support toward high-margin products.
- Levers whose effect cannot be measured from the store's data (price changes without history,
  refund reduction, new products, new markets) become **experiments**: small, capped, with a success
  criterion and a measurement method. Their effect is never counted in the probability until measured.
- The plan is a dated sequence of steps with weekly milestones (expected cumulative metric with its
  P10–P90 band) and the probability of reaching the goal **with** the plan.
- Every executable step becomes a decision that follows the normal rules: policy engine, owner
  approval, execution, measured outcome. Nothing in a plan executes by itself.
- **When the goal is unlikely**, the product proposes instead: the target reachable at 50% and at
  70%, the deadline that would make the original target `possible`, and the experiments that could
  change the picture.

### 17.4 Market context [H+]

- Muse models with search grounding gather public context: market trends for the store's category,
  its region, and its main competitors' public positioning.
- Shown as **external context with sources**, separate from facts. External figures never enter the
  feasibility computation unless the owner confirms them. Web content is untrusted data: it is
  delimited and can never change instructions or trigger actions.
- Public information only; no personal data about competitors' customers.

### 17.5 Tracking

- Every week: actual versus milestone, status `ahead`, `on_track` or `behind`, step adherence (which
  steps were executed), and the updated probability. Shown in the weekly report.
- While steps due so far wait for the owner's approval, the status is `waiting_for_approval`: the
  plan has not started, so it is neither behind nor a verdict drop, and no revision is proposed;
  the weekly report asks the owner to approve instead.
- A step whose decision is superseded by a decision on the same entity resting on more recent data
  makes the plan propose a revision.
- When the actual falls outside the milestone band for two consecutive weeks, or the probability
  drops by a verdict level, the product proposes a revised plan. The owner decides; the plan never
  changes by itself.

### 17.6 Quality bar

| Metric | Target | Measured by |
| --- | --- | --- |
| Forecast P10–P90 coverage, per horizon (30, 60, 90, 180 days) | 75–85% | Backtest on hold-out stores |
| Probability calibration | Reliability curve within ±10 points per bucket; Brier score reported | Backtest on hold-out stores |
| Plan uplift | Success rate with plan vs without, reported with an interval | Simulator ground truth on hold-out stores |
| Goal golden questions | All pass | `bench/golden/questions.yaml` |
