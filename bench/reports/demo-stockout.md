# Demo: the stockout loop

Run 2026-10-31T02:03:04+00:00 on the demo store seeded from `golden-stockout_on_promoted` (`make demo-seed`: simulator, 14 days before the data end). Meta side: documented-contract fake (no sandbox credentials).

Before the loop the store has a budget -30% decision measured, a budget +20% decision measured, and the alert's investigation `fb769338-ab26-4574-9038-147e83e6505d`.

1. Alert: `inc-0806cd14e96b`, level **critical** (profitability). Its decision `b5b7a8b9-16cb-4b1f-86ba-54e9fce0750a`, pending, has 3 options; recommended `pause_until_restock` (net-profit change over 14 days, P10 / P50 / P90: 611.6300 / 632.7400 / 654.5400 USD).
2. Approved through the email link: opening it left the decision `proposed`; confirming it made it `approved`; the same link replayed: HTTP 409.
3. Pause executed: 1cfe53f4-ac3e-42fb-80b0-6516ecfee8cb on meta; Meta mutating calls: 2.
4. Seven days later (the pause's observation window) the supplier restocks.
5. Rollback requested through the API: the campaigns resume.
6. Outcome of the pause (synthetic control, 7 days):

| Action | Status | Effect P10 / P50 / P90 | Predicted P10 / P50 / P90 | Pre-period days, relative error, R2 |
| --- | --- | --- | --- | --- |
| `1cfe53f4` | measured (measured) | 266.23 / 317.21 / 405.07 | 302.12 / 316.17 / 330.93 | 40, 0.2770, -0.0683 |

7. Final decision status: `measured`. Journal:

| At | Kind | Summary |
| --- | --- | --- |
| 2026-10-31T02:03:07 | decision | status=measured |
| 2026-10-31T02:03:07 | approval | verdict=approved, channel=api |
| 2026-10-31T02:03:07 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-31T02:03:09 | outcome | status=measured, reason=measured |
| 2026-10-31T02:03:10 | decision | status=measured |
| 2026-10-31T02:03:10 | approval | verdict=approved, channel=api |
| 2026-10-31T02:03:11 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-31T02:03:12 | outcome | status=measured, reason=measured |
| 2026-10-31T02:03:13 | incident | alert=critical |
| 2026-10-31T02:03:13 | incident | alert=watchlist |
| 2026-10-31T02:03:17 | decision | status=measured |
| 2026-10-31T02:03:48 | approval | verdict=approved, channel=email |
| 2026-10-31T02:03:48 | action | status=executed, kind=pause_campaign, provider=meta |
| 2026-10-31T02:03:50 | action | status=executed, kind=resume_campaign, provider=meta |
| 2026-10-31T02:03:51 | outcome | status=measured, reason=measured |

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
