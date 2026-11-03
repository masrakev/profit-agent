# Page 6 — Goals: screens

Each sheet puts the app's light page (left) next to its dark one (right), each page whole, at
1280 px. The raw screenshots are in `app/`, with the fan chart's hover in both themes. They were
taken with Playwright on a fresh `make demo-seed`, with the API replaying its recorded model
exchanges.

| Sheet | Figma frame |
| --- | --- |
| [goals.png](goals.png) | Desktop · Goals: not available |
| [decisions.png](decisions.png) | Desktop · Decisions: not available |

`tasks/design/` holds no exports, and `docs/screens/figma/` has no Goals or Decisions frame, so
these pages follow the style guide and the components of the earlier pages.

## What the Goals page shows

- **Set a goal** by text or voice, in the composer: Ask restates a goal question as a draft goal
  (`goal_id`), shown with "Confirm this goal"; anything else is sent back to the conversation.
- **Your goal**: the restatement with its facts and names, what the owner said, and its status.
- **Within reach?**: the verdict in words; up to 90 days the chance of reaching it (a fact),
  beyond it the band it lies in and no single chance; the low-evidence reasons; the forecast at
  the deadline if nothing changes; the gap to the target; quarterly checkpoints when the API gives
  them.
- **The plan**: the milestones week by week as a fan (P10 to P90, the most likely path), the
  measured weeks as dots, the target as a dashed line; at the deadline, without and with the plan
  on one axis, and the chance of reaching the target without and with it; the profit the plan
  adds; the proposed revision and why; the steps, the superseded one struck through with the
  decision that replaced it (opening it); the experiments; the plan's assumptions.
- **Week by week**: each weekly check with the actual against the plan's range and the chance now,
  including the weeks waiting for the owner's approval, and the revision proposed.

## Gaps the API leaves (not fixed here)

1. **Chances read as ratios**: the chance facts display as "0.48× to 0.51×", not as percentages.
   The frontend shows the API's text as it is.
2. **No path without the plan**: the API gives the forecast without the plan only at the deadline,
   so the fan shows the plan's path alone, and "without the plan" is compared at the deadline.
3. **Progress after a supersession**: the weekly check of Sep 15 lists the superseded step as still
   awaiting approval, while the revision of the same day says it was superseded.
4. **A planned goal's restatement** still ends with "Confirm it to see whether it is reachable."
5. **390 px**: the app shell does not collapse its rail yet (the responsive pass), so narrow
   screenshots are not useful for any page.
