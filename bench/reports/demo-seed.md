# Demo store

Seeded 2026-11-02T09:59:26+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `695ddbb6-710e-4b29-9a22-5c2c507f278c` is pending.
- Investigation `8a769ed9-9c76-42ca-83ce-828485b61e75`, with its step trace.
- Briefings: daily `e8852481-5795-441f-bee4-b45b28858f59`, weekly `5e0fc129-082c-4a76-9c7d-40a8528802e6`, monthly `4313c17e-f262-4162-b231-a7646b3ba3d4`.
- Goal `e7bab2cb-fd42-4e08-bcd9-d75b9bb71c79`: net profit over the next 90 days; plan `52cc685f-4597-48f4-9027-337fce33e8e6` accepted (`scale_profitable`, `reallocate_budget`); its due steps' decisions: `52e72fd0` proposed, `7a82bc6f` superseded (superseded: the alert's decision acts on the same campaign, on more recent data); revisions proposed: 1.

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Awaiting approval | Revision proposed |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | waiting_for_approval | stretch | 2 | 0 | 2 | no |
| 14 | waiting_for_approval | possible | 2 | 0 | 2 | no |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `a07c21a2` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `31e34f5d` | budget +20% | measured (measured) | -773.37 / -203.15 / 383.68 | 0.3716 |

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
| facts | 4492 |
| audit_log | 24 |
