# Pages 2 and 3 — The conversation, decisions and the email approval page: screens next to Figma

Each sheet puts the app next to the matching Figma frame: the app on the left (light on top, dark
below), Figma on the right. Where Figma has no frame for a screen, or none could be fetched, the
sheet puts the app's light (left) and dark (right) side by side. The raw screenshots are in `app/`,
the Figma exports in `../figma/`.

They come from `node frontend/scripts/screens.mjs 2-3`, on the demo store (`make demo-seed`), with:

- the API given an `APPROVAL_LINK_SECRET` (the email links) and run with `LLM_MODE=live` for the
  one question asked (about $0.11 with the investigation it led to);
- the executor worker running (`python -m app.executor --loop 5`): the demo store's actions go to
  the simulator;
- `SCREENS_EXPIRED_LINK`, an approval link made by the backend's own `create_link` dated two days
  back, for the expired link's page.

The script approves two of the demo store's decisions (one from its email link, one in the
conversation): re-seed the demo store afterwards.

| Sheet | Figma frame |
| --- | --- |
| [chat-brief.png](chat-brief.png) | Dark · Morning brief; header and composer exports (no light frame fetched) |
| [chat-investigation.png](chat-investigation.png) | none: "What I checked" opened from the brief |
| [chat-decision.png](chat-decision.png) | the light permission frame (the decision in the conversation), Dark · Permission card |
| [decision-card.png](decision-card.png) | Permission card, light and dark |
| [decision-live.png](decision-live.png) | none: approved in the conversation, then done with the platform's state read back |
| [ask.png](ask.png) | the composer only: recording, the work as it streams, the answer |
| [approval.png](approval.png) | none: a link opened, approved, used again, decided in the app, replaced, expired |

The Figma MCP server is still at its plan's call limit: the light Morning brief, the investigation,
Ask, voice and the email approval page frames could not be fetched. The light "permission in the
conversation" frame was fetched before the limit, and is now in `../figma/permission-workspace.png`.

## Differences

### On purpose (Task 7 rules and adjustments)

1. **Real data only.** The brief's headline, narrative and numbers are the demo store's briefing;
   Figma's "Good morning. 1 thing needs you today." and "$4,120 down 18%" are sample copy. The
   answer, the investigation's checks and the decision's options are the API's too.
2. **The decision opened from "See options"** comes without Figma's intro ("A small pause. A
   better use of your money." and its explanation): that text was written for the frame, and the
   API has none for a decision. Figma's "See the numbers behind this" is replaced by every number
   being clickable (rule 2).
3. **The decision's period** reads "Compared with doing nothing, Sep 15 – Sep 28, 2026", the
   period of the do-nothing fact, rather than "over 14 days". Option labels name the campaign
   ("Cut the daily budget of 'Trail Jacket — Prospecting' by 30%"). The prepare-only option
   ("Prepare a reorder of Trail Jacket") has no estimate, so no range.
4. **Verified seal** on the weekly picture, the answer and the permission card (adjustment 3).
5. **Safety checks** come from the policy preview of the recommended option's actions; when one
   blocks it, the line is red and Approve is disabled.
6. **After approval** the card follows the decision live ("Approved: starting", "Carrying it out",
   "Done") and ends with the state the executor read back from the platform ("The ad platform
   reports the campaign paused.").
7. **The email approval page** only previews what the link would decide (mail scanners open
   links); the owner confirms with a button. Beyond the spending caps it points to the app. A link
   used again, to a decision decided in the app, replaced or expired, says so without a button.
8. **Contrast tokens and the sidebar** as on page 1 (the dark Approve is `#1F6BFA`, Figma's
   `#4C8DFF` fails AA with white text).

### Found while taking these screens

1. **Spoken questions fail on the demo store (backend; needs your approval).** The transcription
   endpoint refuses any recognition keyword over 30 characters ("ASR keyword 1 exceeds the maximum
   length of 30 characters"); the backend allows 40 (`MAX_KEYWORD_CHARS` in
   `backend/app/agent/llm/transcribe.py`). Two of the demo campaign names given in the backend
   task are longer ("Layers & Camp Kitchen — Lookalike" is 33), so every spoken question there
   ends with "The answer could not be completed". The fix is `MAX_KEYWORD_CHARS = 30` (a longer
   name is already left out, not cut). Until then the sheets show the recording and a typed
   question; the "what was heard, then the answer" screen is missing.
2. **The brief's time** is when the briefing was made. On the demo store that is the seed time
   (here 3:16 PM, today), next to the briefing's own date (Tue, Sep 15, the demo data's last day);
   on a real store both are the same morning.
3. **The brief's narrative repeats the money at stake** ("costing about $5,743 to $6,469 per month
   out of about $5,743 to $6,469 at stake"): the briefing's text, from the backend.
4. **Live answers vary.** Asked "What was my net profit last week, and which campaign cost me the
   most?", this run answered the profit and could not name the campaign (flagged "Little
   evidence"); an earlier run named "Layers & Camp Kitchen — Lookalike" with $517 of spend.
5. **The investigation has no duration or cited facts in its API** (reported before):
   the steps are shown without "took 12 s", and facts it cites are fetched one by one.

Fixed in the app while taking them: a link to a decision no longer waiting offered "Approve" until
the confirmation was refused; a second email link opened in the same tab showed the first link;
a recorded question kept "Listening to your question…" after its answer failed.
