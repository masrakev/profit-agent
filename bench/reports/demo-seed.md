# Demo store

Seeded 2026-10-31T02:03:57+00:00 by `make demo-seed` from `golden-stockout_on_promoted` (simulator, 28 days before the data end, then two windows of 7 days).

- Store `ed68bb6d-1d14-5b04-af2b-e272de12e862`, owner `owner@example.com` with an API token (printed by the seed).
- Alert `inc-0806cd14e96b`, level **critical** (profitability); its decision `d2c393d4-3a78-463b-b221-bca58ccebfed` is pending.
- Investigation `964faadd-02b1-4629-bac9-13fcbdd15e76`, with its step trace.
- Briefings: daily `dceda2af-cf0b-46ed-92fd-f26512c51f5f`, weekly `81162bd3-96de-4b81-a576-b77f1e35f86e`, monthly `7eb503bf-9174-4779-978b-b95a01bfcfc9`.

Past decisions:

| Decision | Action | Outcome | Effect P10 / P50 / P90 | Relative error |
| --- | --- | --- | --- | --- |
| `d34d7a44` | budget -30% | measured (measured) | 22.66 / 637.23 / 1298.77 | 0.3910 |
| `0f98363d` | budget +20% | measured (measured) | 318.77 / 957.52 / 1805.02 | 0.3247 |

Rows:

| Table | Rows |
| --- | --- |
| incidents | 2 |
| alerts | 1 |
| decisions | 3 |
| actions | 2 |
| outcomes | 2 |
| investigations | 1 |
| investigation_steps | 15 |
| briefings | 3 |
| facts | 4025 |
| audit_log | 17 |
