# Demo store

Seeded 2026-10-30T22:06:37+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `7fb7fcca-0a96-47d5-a9b4-7948cb5ccc5f` is pending.
- Investigation `6549d9a1-abac-4719-a6d1-a5872f8ec4e3`, with its step trace.
- Briefings: daily `bf396106-adbc-4815-987e-9581cb7cbfb7`, weekly `de4dbde0-3106-4c31-9045-b865bc7961fe`, monthly `8a06b1e7-bfe8-4f3d-8fc7-0bcae3fa3cd6`.

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `e61a8037` | budget -30% | measured (measured) | 214.34 / 637.23 / 1107.10 | 0.3910 |
| `44a546fd` | budget +20% | measured (measured) | 528.20 / 957.52 / 1595.59 | 0.3247 |

Rows:

| Table | Rows |
| --- | --- |
| incidents | 2 |
| alerts | 1 |
| decisions | 3 |
| actions | 2 |
| outcomes | 2 |
| investigations | 1 |
| investigation_steps | 18 |
| briefings | 3 |
| facts | 4026 |
| audit_log | 17 |
