# Demo store

Seeded 2026-11-03T13:26:55+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, its owner (`DEMO_STORE_OWNER`) with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `a297dbd1-9791-4a6d-8567-ac9e82964dcf` is pending.
- Investigation `f120835b-20b5-4aaf-bb3b-0d685935e36b`, with its step trace.
- Briefings: daily `62259df8-20f1-4740-a5b7-201116fd283c`, weekly `86afe247-3b8a-40a0-9d07-4ff77b1cdb9f`, monthly `65e42537-6aed-4fc6-bff8-0893b97e9194`.
- Goal `08f49b0e-074f-4cd0-98d5-adabadeb9387`: net profit over the next 90 days; plan `bb27d2a4-7ee7-4141-a9b9-a226c9409c71` accepted (`scale_profitable`, `reallocate_budget`); its due steps' decisions: `9b7c47ef` proposed, `35c0740c` superseded (superseded: the alert's decision acts on the same campaign, on more recent data); revisions proposed: 1.
- Goal `267331b5-1322-43e0-ae9b-eaca06484418`: net profit over the next 180 days, confirmed (beyond 90 days: a band of verdicts and quarterly checkpoints).

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Awaiting approval | Revision proposed |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | waiting_for_approval | stretch | 2 | 0 | 2 | no |
| 14 | waiting_for_approval | possible | 2 | 0 | 2 | no |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `b6da889b` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `b57ce69e` | budget +20% | measured (measured) | -773.37 / -203.15 / 383.68 | 0.3716 |

Rows:

| Table | Rows |
| --- | --- |
| incidents | 2 |
| alerts | 1 |
| decisions | 5 |
| actions | 2 |
| goals | 2 |
| goal_plans | 1 |
| goal_steps | 2 |
| goal_progress | 3 |
| outcomes | 2 |
| investigations | 1 |
| investigation_steps | 20 |
| briefings | 3 |
| facts | 4703 |
| audit_log | 26 |
