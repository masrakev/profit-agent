# Demo: the stockout loop

Run 2026-10-30T09:19:03+00:00 on `golden-stockout_on_promoted` (simulator, 14 days before the data end). Meta side: documented-contract fake (no sandbox credentials).

1. Alert: `inc-0806cd14e96b`, level **critical** (profitability).
2. Decision `60aa10e4-5817-4aa3-ba43-37048d0c4362` proposed with 3 options; recommended `pause_until_restock` (net-profit change over 14 days, P10 / P50 / P90: 570.5700 / 592.1700 / 613.9200 USD).
3. Approved through the email link: decision status `approved`; the same link replayed: HTTP 409.
4. Pause executed: 558abf36-267d-44cf-854e-39e6b1b8789a on meta; Meta mutating calls: 2.
5. Seven days later (the pause's observation window) the supplier restocks.
6. Rollback requested through the API: the campaigns resume.
7. Outcome of the pause (synthetic control, 7 days):

| Action | Status | Effect P10 / P50 / P90 | Predicted P10 / P50 / P90 | Pre-period days, relative error, R2 |
| --- | --- | --- | --- | --- |
| `558abf36` | measured (measured) | 212.19 / 245.06 / 330.07 | 281.27 / 296.01 / 310.75 | 40, 0.2879, -0.0578 |

8. Final decision status: `measured`. Journal:

| At | Kind | Summary |
| --- | --- | --- |
| 2026-10-30T09:19:08 | incident | alert=critical |
| 2026-10-30T09:19:08 | incident | alert=watchlist |
| 2026-10-30T09:19:15 | decision | status=measured |
| 2026-10-30T09:19:15 | approval | verdict=approved, channel=email |
| 2026-10-30T09:19:16 | action | status=executed, kind=pause_campaign, provider=meta |
| 2026-10-30T09:19:18 | action | status=executed, kind=resume_campaign, provider=meta |
| 2026-10-30T09:19:20 | outcome | status=measured, reason=measured |

Meta Graph API calls (fake, documented contract):

- GET /120200000000001 {'fields': 'status,effective_status,daily_budget,account_id'}
- GET /120200000000001 {'fields': 'status,effective_status,daily_budget,account_id'}
- POST /120200000000001 {'status': 'PAUSED', 'execution_options': '["validate_only"]'}
- GET /120200000000001 {'fields': 'status,effective_status,daily_budget,account_id'}
- POST /120200000000001 {'status': 'PAUSED'}
- GET /120200000000001 {'fields': 'status,effective_status,daily_budget,account_id'}
- GET /120200000000001 {'fields': 'status,effective_status,daily_budget,account_id'}
- GET /120200000000001 {'fields': 'status,effective_status,daily_budget,account_id'}
- POST /120200000000001 {'status': 'ACTIVE', 'execution_options': '["validate_only"]'}
- GET /120200000000001 {'fields': 'status,effective_status,daily_budget,account_id'}
- POST /120200000000001 {'status': 'ACTIVE'}
- GET /120200000000001 {'fields': 'status,effective_status,daily_budget,account_id'}
