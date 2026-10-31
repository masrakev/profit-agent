# Demo: the stockout loop

Run 2026-10-31T15:57:58+00:00 on the demo store seeded from `golden-stockout_on_promoted` (`make demo-seed`: simulator, 14 days before the data end). Meta side: documented-contract fake (no sandbox credentials).

Before the loop the store has a budget -30% decision measured, a budget +20% decision measured, the alert's investigation `0bc2a1cb-e64d-4f90-9389-6b20855ebdf0`, and a goal `6838ebb1-e6cd-4908-ab3a-02f3390af33c` whose accepted plan's steps are decisions pending the owner's approval (2), tracked weekly.

1. Alert: `inc-0806cd14e96b`, level **critical** (profitability). Its decision `68b85436-f3d1-42e2-90b4-584e9b067fe1`, pending, has 3 options; recommended `pause_until_restock` (net-profit change over 14 days, P10 / P50 / P90: 611.6300 / 632.7400 / 654.5400 USD).
2. Approved through the email link: opening it left the decision `proposed`; confirming it made it `approved`; the same link replayed: HTTP 409.
3. Pause executed: 989a542b-87f8-4bf1-aa0c-ad99eac2fe9c on meta; Meta mutating calls: 2.
4. Seven days later (the pause's observation window) the supplier restocks.
5. Rollback requested through the API: the campaigns resume.
6. Outcome of the pause (synthetic control, 7 days):

| Action | Status | Effect P10 / P50 / P90 | Predicted P10 / P50 / P90 | Pre-period days, relative error, R2 |
| --- | --- | --- | --- | --- |
| `989a542b` | measured (measured) | 266.11 / 317.21 / 405.82 | 302.12 / 316.17 / 330.93 | 40, 0.2770, -0.0683 |

7. Final decision status: `measured`. Journal:

| At | Kind | Summary |
| --- | --- | --- |
| 2026-10-31T15:58:11 | decision | status=proposed |
| 2026-10-31T15:58:11 | decision | status=proposed |
| 2026-10-31T15:58:21 | decision | status=measured |
| 2026-10-31T15:58:21 | approval | verdict=approved, channel=api |
| 2026-10-31T15:58:21 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-31T15:58:26 | outcome | status=measured, reason=measured |
| 2026-10-31T15:58:30 | decision | status=measured |
| 2026-10-31T15:58:31 | approval | verdict=approved, channel=api |
| 2026-10-31T15:58:32 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-31T15:58:39 | outcome | status=measured, reason=measured |
| 2026-10-31T15:58:54 | incident | alert=critical |
| 2026-10-31T15:58:54 | incident | alert=watchlist |
| 2026-10-31T15:59:06 | decision | status=measured |
| 2026-10-31T16:00:09 | approval | verdict=approved, channel=email |
| 2026-10-31T16:00:10 | action | status=executed, kind=pause_campaign, provider=meta |
| 2026-10-31T16:00:14 | action | status=executed, kind=resume_campaign, provider=meta |
| 2026-10-31T16:00:17 | outcome | status=measured, reason=measured |

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
