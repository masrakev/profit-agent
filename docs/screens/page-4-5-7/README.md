# Pages 4, 5 and 7 — Today, Decisions and the Journal: screens

Each sheet puts the app's light page (left) next to its dark one (right), each page whole. The raw
screenshots are in `app/`. They come from `node frontend/scripts/screens.mjs 4-5-7` on the demo
store (`make demo-seed`), with the API replaying its recorded model exchanges.

| Sheet | Figma frame |
| --- | --- |
| [today.png](today.png) | Desktop · Today: not fetched |
| [decisions.png](decisions.png) | Desktop · Decisions: not fetched |
| [journal.png](journal.png) | Desktop · Journal: not fetched |

The Figma MCP server is still at its plan's call limit, and `tasks/design/` holds no PNG exports,
so these pages follow the style guide and the components of pages 1 to 3, without a frame to
compare with. Exports of the Today, Decisions and Journal frames (light and dark) would let the
next review put them side by side.

## What each page shows

- **Today**: the store's day as `GET /overview` assembles it from facts, with the brief's own
  section components (the picture with the money at stake as a range, what needs the owner, the
  pending decisions, the data notice), then what moved net profit this week (`GET /profit-bridge`):
  the change and each driver as clickable facts, on bars from the centre plotted from the API's
  values; drivers inside their noise band say "Within its usual variation".
- **Decisions**: every decision by where it stands (waiting for you, in progress, done, closed),
  where it came from and when, the range it expected and, once measured, the measured range on the
  same axis. Earned autonomy lists, per kind of action, how far the agent may act alone (SPEC
  section 7's levels); "Always allow" appears only when the trust ledger proposes a promotion (none
  does on the demo store).
- **Journal**: newest first, day by day in the store's time zone: problems found ("What I checked"
  opens the investigation in the conversation), decisions proposed with their status now, the
  owner's answers and their channel, what was carried out with the platform's state read back,
  and the measured effect as a fact.

Opening a decision or an investigation from these pages puts it in the conversation and goes there.

## What the API does not give yet (to decide; no backend change made)

1. **The prediction-vs-measured verdict.** Adjustment 4 asks for it on a measured decision. The
   API serves the predicted range (the chosen option's impact fact) and the measured one (the
   outcome's effect fact), but not whether the effect fell inside the prediction, or above, or
   below. The frontend may not compare numbers, so the page shows both ranges on one axis and says
   nothing more. Proposed: a verdict on the outcome, in words, from the backend.
2. **A decision's outcome.** `DecisionView` has none: the page finds each measured effect in the
   journal's outcome entries (one more request). Proposed: the outcome on the decision (its effect
   fact, status, window and verdict).
3. **Predictions of decisions the owner asked for.** Their options carry no impact fact: their
   prediction exists only as raw numbers inside the outcome, which the trust ledger compares. So
   the two measured demo decisions show the measured range alone. Proposed: the prediction as an
   estimate fact.
4. **Earned autonomy's progress.** "1 of 10 confirmations before I can ask to do this alone"
   cannot be written: `GET /trust` gives raw decimals (`mean_abs_error`, `inside_share`), no count
   of predictions that held, and not the threshold (10 measured outcomes, 75% inside the range);
   a proposal is free text without the level it proposes. Proposed: confirmations, the number
   required, the sentence as the backend writes it, and the proposed level. Until then "Always
   allow" leads to Settings (page 8).
5. **The journal's amounts and names.** A budget change's before and after are raw minor units,
   not facts, so the line says what was carried out without the amounts; entries name campaigns
   only by id, so each line is named through its decision (the decisions list, one request).
   Entries made in the same second (the demo's seeded history) follow the API's order by kind.

## Seen while building

- At 19:37, two minutes after a fresh `make demo-seed`, the demo's Trail Jacket pause was approved
  through the API (channel `api`, the demo owner) and executed in the same second. Nothing I ran
  then approves decisions (the test suites use their own databases, the in-app browser was on the
  approval page's "not valid" screen), so its origin is not known. The screens show the store in
  that state: the pause done, the budget raise for Trail Essentials waiting.
