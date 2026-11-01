# Demo store

Seeded 2026-11-01T03:49:49+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `8b35244e-7056-46e3-9573-063db9b3fcec` is pending.
- Investigation `1a7f4566-8f2d-49b4-832d-eb65828443c0`, with its step trace.
- Briefings: daily `797d432b-491a-44e3-ae4d-0e25a7de892b`, weekly `3b11fef7-24a4-462d-baa6-a5d154794c24`, monthly `cc10cd1f-726e-46ce-b236-976931c618cf`.
- Goal `986aaf0c-6daa-4f92-be99-3a84078975cb`: net profit over the next 90 days; plan `2d16849c-4104-4ce9-8773-0418d23d1ed0` accepted (`scale_profitable`, `reallocate_budget`); its due steps' decisions: `ef5fcd55` proposed, `387925f9` superseded (superseded: the alert's decision acts on the same campaign, on more recent data); revisions proposed: 1.

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Pending |
| --- | --- | --- | --- | --- | --- |
| 7 | on_track | stretch | 2 | 0 | 2 |
| 14 | on_track | possible | 2 | 0 | 2 |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `39b0fb73` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `92312877` | budget +20% | measured (measured) | -773.37 / -203.15 / 383.68 | 0.3716 |

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
| investigation_steps | 17 |
| briefings | 3 |
| facts | 4493 |
| audit_log | 24 |
