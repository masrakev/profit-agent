# Demo store

Seeded 2026-11-03T00:32:46+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `b8a8fb97-575f-44b1-903d-0fac614b81ca` is pending.
- Investigation `59196a7c-78d3-4636-bf82-6d1b4e9aff5c`, with its step trace.
- Briefings: daily `5e4e00f0-4e1a-4999-9346-e830fa3a3f50`, weekly `301a4a45-19db-45bf-8dec-35664659c56f`, monthly `2ce7fb87-6344-485e-97f8-27ca13493f7e`.
- Goal `b18da45e-e3f6-4649-ab88-abf60b975534`: net profit over the next 90 days; plan `92a52bc7-0d25-4eab-b3f9-ec40fb18528b` accepted (`scale_profitable`, `reallocate_budget`); its due steps' decisions: `145b1a58` proposed, `10edd4fa` superseded (superseded: the alert's decision acts on the same campaign, on more recent data); revisions proposed: 1.

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Awaiting approval | Revision proposed |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | waiting_for_approval | stretch | 2 | 0 | 2 | no |
| 14 | waiting_for_approval | possible | 2 | 0 | 2 | no |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `d792cd8e` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `da76d30c` | budget +20% | measured (measured) | -773.37 / -203.15 / 383.68 | 0.3716 |

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
| investigation_steps | 21 |
| briefings | 3 |
| facts | 4580 |
| audit_log | 24 |
