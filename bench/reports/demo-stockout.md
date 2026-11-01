# Demo: the stockout loop

Run 2026-11-01T03:50:39+00:00 on the demo store seeded from `golden-stockout_on_promoted` (`make demo-seed`: simulator, 14 days before the data end). Meta side: documented-contract fake (no sandbox credentials).

Before the loop the store has a budget -30% decision measured, a budget +20% decision measured, the alert's investigation `1a2d44d7-739b-45b9-b6b7-6c582a5aa76c`, and a goal `ab5e0fb6-1cba-4575-87a1-b78bf0f27e78` whose accepted plan's steps are decisions pending the owner's approval (2), tracked weekly.

1. Alert: `inc-0806cd14e96b`, level **critical** (profitability). Its decision `61de25ee-b976-4c2f-823b-89ee31b88737`, pending, has 3 options; recommended `pause_until_restock` (net-profit change over 14 days, P10 / P50 / P90: 613.1800 / 634.4000 / 654.3300 USD).
2. Approved through the email link: opening it left the decision `proposed`; confirming it made it `approved`; the same link replayed: HTTP 409.
3. Pause executed: 6b202645-7553-4b4d-be40-442f300be505 on meta; Meta mutating calls: 2.
4. Seven days later (the pause's observation window) the supplier restocks.
5. Rollback requested through the API: the campaigns resume.
6. Outcome of the pause (synthetic control, 7 days):

| Action | Status | Effect P10 / P50 / P90 | Predicted P10 / P50 / P90 | Pre-period days, relative error, R2 |
| --- | --- | --- | --- | --- |
| `6b202645` | measured (measured) | 222.63 / 270.81 / 352.78 | 301.01 / 316.61 / 331.24 | 40, 0.2897, -0.1763 |

7. Final decision status: `measured`. Journal:

| At | Kind | Summary |
| --- | --- | --- |
| 2026-10-18T03:50:46 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-18T03:50:46 | approval | verdict=approved, channel=api |
| 2026-10-18T03:50:46 | decision | status=measured |
| 2026-10-25T03:50:46 | action | status=executed, kind=change_budget, provider=simulator |
| 2026-10-25T03:50:46 | approval | verdict=approved, channel=api |
| 2026-10-25T03:50:46 | decision | status=measured |
| 2026-11-01T03:50:42 | decision | status=proposed |
| 2026-11-01T03:50:42 | decision | status=superseded |
| 2026-11-01T03:50:48 | outcome | status=measured, reason=measured |
| 2026-11-01T03:50:52 | outcome | status=measured, reason=measured |
| 2026-11-01T03:50:53 | incident | alert=critical |
| 2026-11-01T03:50:53 | incident | alert=watchlist |
| 2026-11-01T03:50:57 | decision | status=measured |
| 2026-11-01T03:51:24 | approval | verdict=approved, channel=email |
| 2026-11-01T03:51:24 | action | status=executed, kind=pause_campaign, provider=meta |
| 2026-11-01T03:51:25 | action | status=executed, kind=resume_campaign, provider=meta |
| 2026-11-01T03:51:27 | outcome | status=measured, reason=measured |

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
