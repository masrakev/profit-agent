# Demo store

Seeded 2026-11-01T04:01:24+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `d1484740-67d8-4230-9bf0-ba2a61c42b47` is pending.
- Investigation `6842372a-68ed-40d6-869e-bacb84abfbaf`, with its step trace.
- Briefings: daily `52c0bee2-75f1-4e27-bddc-7fcee44253cd`, weekly `b7259535-4f67-4146-a4bc-5f2fd8c407c3`, monthly `538b6f94-af81-4278-937c-2f7d8e3a301c`.
- Goal `79361f7a-f84c-4733-8c0c-faa6a9e4ba28`: net profit over the next 90 days; plan `a15e1688-93da-4d45-85ea-646172e42805` accepted (`scale_profitable`, `reallocate_budget`); its due steps' decisions: `6afea66d` proposed, `e1cf70c3` superseded (superseded: the alert's decision acts on the same campaign, on more recent data); revisions proposed: 1.

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Awaiting approval | Revision proposed |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | waiting_for_approval | stretch | 2 | 0 | 2 | no |
| 14 | waiting_for_approval | possible | 2 | 0 | 2 | no |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `82703203` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `5ddbfbe4` | budget +20% | measured (measured) | -773.37 / -203.15 / 383.68 | 0.3716 |

Rows:

| Table | Rows |
| --- | --- |
| incidents | 2 |
| alerts | 1 |
| decisions | 5 |
| actions | 2 |
| goals | 1 |
| goal_plans | 1 |
| goal_steps | 2 |
| goal_progress | 3 |
| outcomes | 2 |
| investigations | 1 |
| investigation_steps | 15 |
| briefings | 3 |
| facts | 4572 |
| audit_log | 24 |
