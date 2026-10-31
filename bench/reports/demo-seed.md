# Demo store

Seeded 2026-10-31T15:55:45+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `6e9eb963-3e4e-41f4-bf3d-51432af2c51c` is pending.
- Investigation `6e737a98-bdd7-4625-839a-e01d0530f1c7`, with its step trace.
- Briefings: daily `c9083d09-52f2-475d-879f-2d53efd98a20`, weekly `7e285dd8-279e-456b-81b3-d27e74a5d845`, monthly `3e63fc23-8979-4f99-a61c-d4a6220146e6`.
- Goal `5e10592f-2930-4f3f-a459-97e494768387`: net profit over the next 90 days; plan `bcefd299-b501-429e-80c0-0432df636f09` accepted (`scale_profitable`, `reallocate_budget`); its due steps are decisions pending the owner's approval.

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Pending |
| --- | --- | --- | --- | --- | --- |
| 7 | on_track | stretch | 2 | 0 | 2 |
| 14 | on_track | possible | 2 | 0 | 2 |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `195f922e` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `60f77213` | budget +20% | measured (measured) | 318.77 / 957.52 / 1805.02 | 0.3247 |

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
| goal_progress | 2 |
| outcomes | 2 |
| investigations | 1 |
| investigation_steps | 17 |
| briefings | 3 |
| facts | 4560 |
| audit_log | 23 |
