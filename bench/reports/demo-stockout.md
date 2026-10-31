# Demo: the stockout loop

Run 2026-10-30T22:07:38+00:00 on the demo store seeded from `golden-stockout_on_promoted` (`make demo-seed`: simulator, 14 days before the data end). Meta side: documented-contract fake (no sandbox credentials).

Before the loop the store has a budget -30% decision measured, a budget +20% decision measured, and the alert's investigation `0fec8226-e807-4f20-a02a-b0a82a84cf1e`.

1. Alert: `inc-0806cd14e96b`, level **critical** (profitability). Its decision `d77d73d4-8b18-41a3-a981-50ae5ca51f88`, pending, has 3 options; recommended `pause_until_restock` (net-profit change over 14 days, P10 / P50 / P90: 611.6300 / 632.7400 / 654.5400 USD).
2. Approved through the email link: opening it left the decision `proposed`; confirming it made it `approved`; the same link replayed: HTTP 409.
3. Pause executed: 3d7e6d5a-f19c-4a6d-85b7-1d8d13975f53 on meta; Meta mutating calls: 2.
4. Seven days later (the pause's observation window) the supplier restocks.
5. Rollback requested through the API: the campaigns resume.
6. Outcome of the pause (synthetic control, 7 days):

| Action | Status | Effect P10 / P50 / P90 | Predicted P10 / P50 / P90 | Pre-period days, relative error, R2 |
| --- | --- | --- | --- | --- |
| `3d7e6d5a` | measured (measured) | 285.95 / 317.21 / 385.35 | 302.12 / 316.17 / 330.93 | 40, 0.2770, -0.0683 |

7. Final decision status: `measured`. Journal:

| At | Kind | Summary |
| --- | --- | --- |
| 2026-10-30T22:07:43 | decision | status=measured |
| 2026-10-30T22:07:43 | approval | verdict=approved, channel=api |
| 2026-10-30T22:07:43 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-30T22:07:45 | outcome | status=measured, reason=measured |
| 2026-10-30T22:07:47 | decision | status=measured |
| 2026-10-30T22:07:47 | approval | verdict=approved, channel=api |
| 2026-10-30T22:07:47 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-30T22:07:50 | outcome | status=measured, reason=measured |
| 2026-10-30T22:07:52 | incident | alert=critical |
| 2026-10-30T22:07:52 | incident | alert=watchlist |
| 2026-10-30T22:07:57 | decision | status=measured |
| 2026-10-30T22:08:50 | approval | verdict=approved, channel=email |
| 2026-10-30T22:08:50 | action | status=executed, kind=pause_campaign, provider=meta |
| 2026-10-30T22:08:53 | action | status=executed, kind=resume_campaign, provider=meta |
| 2026-10-30T22:08:55 | outcome | status=measured, reason=measured |

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
