# Demo store

Seeded 2026-11-02T19:08:03+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `c8dc5af2-6ca6-4b41-8f7d-76fee3e1a0f6` is pending.
- Investigation `8ecb2777-4bcc-4767-a221-551c859f1498`, with its step trace.
- Briefings: daily `7d715538-b04b-4cf6-b7a6-faa78a36f34d`, weekly `4707e68a-03a2-4cc1-9492-a5b2150f5c54`, monthly `51914d00-520c-473e-a8a0-0ebb00e0ddd8`.
- Goal `a1028c05-2993-43f1-892a-5cf1efa397d5`: net profit over the next 90 days; plan `f539cad1-ea00-4c9a-a412-d456d4636de1` accepted (`scale_profitable`, `reallocate_budget`); its due steps' decisions: `3574fb2d` proposed, `6ababa3d` superseded (superseded: the alert's decision acts on the same campaign, on more recent data); revisions proposed: 1.

Goal tracking:

| Day | Status | Verdict | Steps due | Done | Awaiting approval | Revision proposed |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | waiting_for_approval | stretch | 2 | 0 | 2 | no |
| 14 | waiting_for_approval | possible | 2 | 0 | 2 | no |

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `e929c45f` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `dbe8459d` | budget +20% | measured (measured) | -773.37 / -203.15 / 383.68 | 0.3716 |

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
| facts | 4553 |
| audit_log | 24 |
