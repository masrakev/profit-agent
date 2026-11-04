# Merit: design

How the web app looks, moves and is checked. The values live in
`frontend/src/styles/index.css` (the only place a value is written); this page says what they are
for. Read it before any interface work and pass its checklist before calling the work done.

## 1. Principles

1. **Calm, confident, editorial.** The owner reads the app like a good brief: typography and
   whitespace carry the hierarchy, not boxes. Lines of text stay under 65 characters wide.
2. **Light by default, dark as finished.** Near-white and near-black, monochrome. The app opens
   light (it reads like a report, and holds on a projector); dark is one click away in the rail and
   remembered, and "system" can be chosen. Every screen is checked in both with the same care.
3. **One accent, used rarely: Meta blue.** It marks the agent (its mark), keyboard focus, the primary
   action of a screen, the most likely value of a range and a lit verdict. Nothing else is blue.
4. **Colour means state, and only as a dot or as words.** Good, warning and danger appear as a
   6 px dot beside words, or as text in their `-ink` form. Never a coloured border, a left stripe,
   a filled badge or a coloured bar.
5. **Cards only for what the owner acts on.** The approval moment and a goal waiting for
   confirmation are cards. Everything else is lists, rows and sections over hairlines.
6. **Numbers are the API's.** Every number shown is a fact's own text, opening its proof. The
   frontend never rounds, formats or computes one (Task 7, rule 1). A range reads once.
7. **The agent is one mark, used where it means something.** A range with its median, the
   product's own sign: in the brand, the status line, the Working block and the approval card,
   nowhere as decoration. Idle it rests; working, its median moves; waiting for you, a small dot.
   Working, it names the Meta model it works with, as the API reports it.
8. **Never a blank page.** Wherever there is a composer, questions drawn from the store's situation
   sit above it. An empty list says what will appear and what to do now.
9. **Decisions live in Decisions.** The conversation holds the brief, questions and answers.
   Anything that asks the owner to decide opens on the Decisions page, its row expanded.

## 2. Tokens

Semantic utilities only (`bg-surface`, `text-ink`, `border-line`…). A new value is a new token in
the CSS and a line here, in the same change.

### Colour

| Token                       | Dark              | Light             | Use                                                    |
| --------------------------- | ----------------- | ----------------- | ------------------------------------------------------ |
| `canvas`                    | #0b0b0c           | #fafafa           | page background, the rail                              |
| `surface`                   | #131315           | #ffffff           | the few cards, popovers                                |
| `subtle`                    | #1b1b1e           | #f2f2f3           | hover, the owner's bubble, skeletons, details panels   |
| `line`                      | #242427           | #e5e5e7           | hairlines, outlines                                    |
| `input`                     | #6c6c74           | #85858d           | a control's only boundary (3:1)                        |
| `ink`                       | #ededef           | #0f0f10           | text                                                   |
| `ink-muted`                 | #a1a1a8           | #5d5d64           | secondary text, labels, icons                          |
| `accent-mark`               | #4c8dff           | #0866ff           | blue graphics: the mark, range marks, focus, lit band  |
| `accent-ink`                | #6aa1ff           | #065de6           | blue text (rare: the most likely value, "Recommended") |
| `accent-soft`               | #152238           | #ebf3ff           | the track of a range                                   |
| `accent-fill` / `on-accent` | #0866ff / #ffffff | #0866ff / #ffffff | the primary action (4.8:1)                             |
| `good` / `good-ink`         | #3fb862 / #5fd283 | #1f8f4c / #18793b | dot / text                                             |
| `warning` / `warning-ink`   | #e2a72c / #f0c25e | #b07a06 / #855600 | dot / text                                             |
| `danger` / `danger-ink`     | #f0525f / #ff8089 | #d93142 / #be1f30 | dot / text                                             |

Every text token is at least 4.5:1 on canvas, surface and subtle in its theme; every graphic token
at least 3:1 (checked with the WCAG formula when the values were set).

### Type

Geist (Regular for text, Medium and Semibold for titles) and Geist Mono for timestamps,
identifiers and dates in metadata; both self-hosted (`@fontsource-variable`). Six sizes, no more:

| Size                | Token          | Use                                            |
| ------------------- | -------------- | ---------------------------------------------- |
| 36 / 1.12, −0.035em | `text-proof`   | the day's headline (brief, Today) from `md` up |
| 24 / 1.25, −0.025em | `text-title`   | page titles, a verdict, headlines on phones    |
| 18 / 1.35, −0.015em | `text-heading` | a goal's restatement, the approval question    |
| 15 / 1.6            | `text-body`    | running text, row titles, buttons              |
| 13 / 1.5            | `text-small`   | secondary lines, section labels                |
| 12 / 1.4            | `text-label`   | metadata, statuses, timestamps                 |

The other size names (`brand`, `nav`, `caption`, `tiny`, shadcn's `xs` to `xl`) alias these.
Amounts are set in tabular figures (`[data-fact]`, `time` and `.tabular-nums` get them by default).

### Space, radii, elevation, motion

- **Space:** the 4 px grid; 8 between related lines, 16 to 20 inside a row, 40 to 48 between
  sections (`gap-10`, `gap-12`). Content column 720 px; 16 px gutters on phones.
- **Radii:** 2 (bars), 8 (controls, marks), 12 (the few cards), full (pills, the agent's mark).
- **Elevation:** one level, `shadow-float`, for what floats: the composer, popovers, the proof
  sheet, the approval moment. Nothing else casts a shadow.
- **Motion:** 150 to 250 ms, eased out (`--ease-out`). The agent's median moves while it works
  (`animate-estimate`); lists reveal in a stagger (`data-stagger`, 40 ms apart). Everything stops
  under `prefers-reduced-motion`.

## 3. Components

One component per concept; check `frontend/src/ui` and `frontend/src/charts` before adding one.

| Concept                   | Component                                           | Do                                                                                                              | Don't                                    |
| ------------------------- | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| App shell                 | `shell/AppShell`, `NavRail`, `TopBar`               | rail on `md` up, a drawer on phones                                                                             | put content outside the 720 px column    |
| Agent mark                | `ui/AgentMark`                                      | a range and its median; `idle`, `working`, `waiting`; sm, md, lg; brand, status, Working, approval only         | an avatar beside every message           |
| Status line               | `shell/AgentStatus`                                 | three levels in words beside the mark                                                                           | show counts the API did not give         |
| Composer                  | `shell/Composer` + `shell/Suggestions`              | text and voice; suggestions until the first question                                                            | leave it on a blank page                 |
| Section header            | `ui/Section`                                        | a muted label over a hairline, an aside on the right                                                            | uppercase, tracked-out eyebrows          |
| List row                  | rows in each page                                   | hairline below, 16 to 20 px padding, status on the right                                                        | boxes around rows                        |
| Status                    | `ui/StatusPill`                                     | a 6 px dot and words                                                                                            | a filled or coloured badge               |
| Evidence                  | `AnswerMessage` (Evidence)                          | named facts with their values under the Verified seal, four then all                                            | numbers without a name                   |
| Verified seal             | `facts/VerifiedSeal`                                | on what carries numbers; opens how they were made                                                               | on text without facts                    |
| Money range               | `charts/RangeBar`                                   | "low to high" once, most likely beside, the track below; `range={false}` under a sentence that already reads it | repeat the endpoints                     |
| Prediction vs measurement | `charts/CompareRanges` + the backend's verdict text | one axis for both, the verdict as written                                                                       | compare numbers in the frontend          |
| Trust progress            | `charts/TrustMeter` + the API's sentence            | ticks for the threshold, earned ones lit                                                                        | a percentage the API did not give        |
| Verdict band              | `charts/VerdictBand`                                | unlikely to likely, the verdict or its interval lit                                                             | a single chance beyond 90 days           |
| Goal thread               | `GoalsPage` (Thread)                                | ahead on a dashed rule, then newest first: a mono date, a title, the status on the right                        | dates the API did not give               |
| Conversation topic        | `ConversationComposer` (About chip)                 | the decision or goal named above the composer, its own questions, × to ask about the store again                | context the owner cannot see             |
| Ask from anywhere         | `shell/AskPalette` (⌘K, Ctrl K)                     | a modal over the page: the field focused, about the decision or goal on screen (a pill to turn off)             | a second composer on the page itself     |
| Conversation history      | `ChatPage` (History)                                | each conversation at `/chat/<id>`, its first question as title, a mono date; New conversation beside            | counts the API did not give              |
| On/off setting            | `ui/Switch` in a settings row                       | saved at once, said in the page's status line; disabled with the reason in the row's hint                       | a Save button for one switch             |
| Approval moment           | `decisions/PermissionCard`                          | the one strong surface: mark, question, option rows, safety, Approve                                            | more than one primary action             |
| Empty state               | `ui/EmptyState`                                     | what will appear and what to do now                                                                             | an apology or a mood                     |
| Loading                   | `ui/Skeleton`                                       | rows in the page's rhythm                                                                                       | a spinner in place of content            |
| Buttons                   | `ui/Button`                                         | primary (Meta blue), secondary (outlined), ghost (bare)                                                         | the accent as a button colour            |

There is no toast yet: an action's outcome is said in place (the decision's row, the goal's
status). Add one as a component here first if a flow needs it.

## 4. Review checklist

Before an interface change is done, at 1440 and 390 px, in dark and light
(`node frontend/scripts/design-shots.mjs <dir>` takes every page and state):

- [ ] Only the six type sizes; large titles tracked tight; amounts in tabular figures.
- [ ] Spacing on the 4 px grid; sections separated by space and hairlines, not boxes.
- [ ] Cards only for what the owner acts on; one elevation; radii from the four.
- [ ] The accent appears only on the agent's mark, focus, the primary action, a range's most likely
      value or a lit verdict; semantic colours only as dots or text.
- [ ] Every number is a fact's text that opens its proof; a range reads once.
- [ ] Text contrast 4.5:1, graphics 3:1, in both themes.
- [ ] Every control reachable by keyboard with a visible 2 px focus ring; the approval moment can
      be completed from the keyboard alone.
- [ ] Motion 150 to 250 ms, and none under reduced motion.
- [ ] Nothing scrolls sideways at 390 px; the rail is a drawer there.
- [ ] Empty, loading and error states exist and say what to do.
- [ ] No error or warning from the app in the browser console.
- [ ] `make web-lint web-test` passes, and every existing test and `data-testid` still holds.
