# Demo store

Seeded 2026-11-03T12:25:41+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `8567065f-5754-433d-b917-dda22578046b` is pending.
- Investigation `b9006261-7202-4513-9f2b-26ef0a6a87d7`, with its step trace.
- Briefings: daily `839b09be-aa09-4969-a97e-ea69d95f4085`, weekly `d84b254a-98df-49ad-af2b-7d6e9f456a43`, monthly `e6fa2652-a5d1-4e70-aa88-7f3681a46983`.
- Goal `df7dffcc-8312-4a38-a593-8d1deaaa2850`: net profit over the next 90 days; plan `964483bb-d084-437b-92bd-e3a2538fce1b` accepted (`scale_profitable`, `reallocate_budget`); its due steps' decisions: `07951cdd` proposed, `5ea881ed` superseded (superseded: the alert's decision acts on the same campaign, on more recent data); revisions proposed: 1.

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Awaiting approval | Revision proposed |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | waiting_for_approval | stretch | 2 | 0 | 2 | no |
| 14 | waiting_for_approval | possible | 2 | 0 | 2 | no |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `88a8954b` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `21c5d9e3` | budget +20% | measured (measured) | -773.37 / -203.15 / 383.68 | 0.3716 |

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
| investigation_steps | 20 |
| briefings | 3 |
| facts | 4520 |
| audit_log | 24 |
