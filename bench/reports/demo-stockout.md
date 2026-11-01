# Demo: the stockout loop

Run 2026-11-01T04:02:23+00:00 on the demo store seeded from `golden-stockout_on_promoted` (`make demo-seed`: simulator, 14 days before the data end). Meta side: documented-contract fake (no sandbox credentials).

Before the loop the store has a budget -30% decision measured, a budget +20% decision measured, the alert's investigation `157b613c-b74a-4baf-b265-4ad2800711e3`, and a goal `b47190db-4d07-4f8e-923c-3bc5f8dfe07e` whose accepted plan's steps are decisions pending the owner's approval (2), tracked weekly.

1. Alert: `inc-0806cd14e96b`, level **critical** (profitability). Its decision `0a062464-15a7-4e1d-af4e-5e87652dc5e0`, pending, has 3 options; recommended `pause_until_restock` (net-profit change over 14 days, P10 / P50 / P90: 613.1800 / 634.4000 / 654.3300 USD).
2. Approved through the email link: opening it left the decision `proposed`; confirming it made it `approved`; the same link replayed: HTTP 409.
3. Pause executed: 5f1ad569-9b35-43cc-b65f-39fbfe66fc88 on meta; Meta mutating calls: 2.
4. Seven days later (the pause's observation window) the supplier restocks.
5. Rollback requested through the API: the campaigns resume.
6. Outcome of the pause (synthetic control, 7 days):

| Action | Status | Effect P10 / P50 / P90 | Predicted P10 / P50 / P90 | Pre-period days, relative error, R2 |
| --- | --- | --- | --- | --- |
| `5f1ad569` | measured (measured) | 224.67 / 264.19 / 352.44 | 301.01 / 316.61 / 331.24 | 40, 0.2897, -0.1763 |

7. Final decision status: `measured`. Journal:

| At | Kind | Summary |
| --- | --- | --- |
| 2026-10-18T04:02:32 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-18T04:02:32 | approval | verdict=approved, channel=api |
| 2026-10-18T04:02:32 | decision | status=measured |
| 2026-10-25T04:02:32 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-25T04:02:32 | approval | verdict=approved, channel=api |
| 2026-10-25T04:02:32 | decision | status=measured |
| 2026-11-01T04:02:26 | decision | status=superseded |
| 2026-11-01T04:02:26 | decision | status=proposed |
| 2026-11-01T04:02:34 | outcome | status=measured, reason=measured |
| 2026-11-01T04:02:38 | outcome | status=measured, reason=measured |
| 2026-11-01T04:02:40 | incident | alert=critical |
| 2026-11-01T04:02:40 | incident | alert=watchlist |
| 2026-11-01T04:02:44 | decision | status=measured |
| 2026-11-01T04:03:16 | approval | verdict=approved, channel=email |
| 2026-11-01T04:03:16 | action | status=executed, kind=pause_campaign, provider=meta |
| 2026-11-01T04:03:18 | action | status=executed, kind=resume_campaign, provider=meta |
| 2026-11-01T04:03:20 | outcome | status=measured, reason=measured |

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
