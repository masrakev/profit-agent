# Demo store

Seeded 2026-11-02T09:26:32+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `308062d8-331b-41ec-a83b-0373ca6a2c25` is pending.
- Investigation `37dde14d-1e89-41b5-b975-d897655be5ae`, with its step trace.
- Briefings: daily `045d755c-c8ff-4fa8-99a0-bb82e7e8d16b`, weekly `9d6bebfa-4d5c-405a-815b-375ae198e006`, monthly `1c33e21a-8f31-4091-920c-e4414a08a910`.
- Goal `c79ebffb-7699-4916-b8fa-9193164fa2a7`: net profit over the next 90 days; plan `d43c6262-5fca-46fb-8f6e-2c65322ba547` accepted (`scale_profitable`, `reallocate_budget`); its due steps' decisions: `21e65ee3` proposed, `9408e0a7` superseded (superseded: the alert's decision acts on the same campaign, on more recent data); revisions proposed: 1.

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Awaiting approval | Revision proposed |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | waiting_for_approval | stretch | 2 | 0 | 2 | no |
| 14 | waiting_for_approval | possible | 2 | 0 | 2 | no |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `eea20d25` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `1602bf56` | budget +20% | measured (measured) | -773.37 / -203.15 / 383.68 | 0.3716 |

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
| facts | 4498 |
| audit_log | 24 |
