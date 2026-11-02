# Page 1 — Foundation: screens next to Figma

Each sheet puts the app (left; light on top, dark below) next to the matching Figma frame (right).
The app runs on the demo store (`make demo-seed`), signed in with "Use the demo store"; the
screenshots come from `node frontend/scripts/screens.mjs`, the raw ones are in `app/`, the Figma
exports in `../figma/`.

| Sheet | Figma frame |
| --- | --- |
| [style-guide.png](style-guide.png) | Style guide · Profit Agent |
| [sign-in.png](sign-in.png) | Account · Sign in (no dark frame in Figma) |
| [shell.png](shell.png) | Desktop · Morning brief (header and composer exports), Dark · Morning brief |
| [exact-proof.png](exact-proof.png) | Desktop · Exact proof, Dark · Exact proof |
| [estimate-proof.png](estimate-proof.png) | Desktop · Estimate proof, the sheet (the dark frame was not fetched) |
| [permission-card.png](permission-card.png) | Permission card, light and dark |

The Figma MCP server reached its plan's call limit during the capture: the light Morning brief, the
Estimate proof frames and the sign-in frame were taken from exports fetched earlier in the same
session (the sign-in frame, the estimate sheet, the header and the composer).

## Differences

### On purpose (Task 7 rules and adjustments)

1. **Contrast tokens (adjustment 5).** Three Figma pairs are under WCAG AA 4.5:1; text uses its own
   tokens: blue text `#065DE6` light (Figma `#0866FF` on `#F0F2F5` is 4.30) and `#5A96FF` dark
   (`#4C8DFF` on the selected rail item `#192A46` is 4.49); the dark filled button `#1F6BFA` with
   white (Figma: white on `#4C8DFF`, 3.20); red text `#D91A3B` light, `#FF6B7D` dark (`#E41E3F` is
   4.11 on `#F0F2F5`, 3.89 on `#16171A`). The red button keeps `#E41E3F` (white on it is 4.61).
   Greys all pass and are unchanged. The style guide sheet shows the added swatches.
2. **Verified seal (adjustment 3)** on the cards that carry numbers (the estimate card, the
   permission card); it opens "Every number here was computed by code from your data" and links to
   the proof. Not in Figma.
3. **Real data only (adjustment 2).** Every number, name and option on the screens is the demo
   store's, from the API: Figma's sample copy ("Northwind Outdoor", "Trail Jacket — Prospecting",
   "+$570 to +$614") is not reproduced. Formats are the API's: `$613.18–$654.33`, with cents, no
   plus sign and an en dash, where Figma writes `+$570 to +$614`.
4. **Lineage in the proof (rule 2).** The proof sheet adds the formula's id and version, the
   period, and "Built from" (the parent facts, each one clickable, with Back).
5. **No invented links or sample data.** The email field starts empty (Figma shows a sample
   address). The sign-in page drops "By continuing, you agree to our Terms and Privacy
   Policy" and the footer's "Privacy" and "Help": those pages do not exist yet. The footer shows the
   product name.
6. **Development build only:** "Use the demo store" under the sign-in form, and the `/style-guide`
   catalogue itself (absent from a production build).

### Waiting for the API (reported, no backend change made)

7. **The store's name.** No endpoint returns it (the session lists store ids): the header and the
   store menu say "Your store" / "YS" where Figma shows "Northwind Outdoor · Demo store" / "NO".
8. **P50 formatted.** A fact formats an estimate as its P10–P90 range only; the bar marks P50 but
   cannot label it (Figma: "+$592" in blue above the mark, and "+$570 · +$592 · +$614" as the
   estimate's value).
9. **Source rows in the proof.** A fact's sources are tables with row counts; Figma lists each daily
   row with its amount, a total, "Last synced today at 7:25 AM" and "Open source in Meta ↗". The
   sheet shows each table and its row count, and a Close button.
10. **Connection health.** The header pill says "Connected" from the API's readiness check; Figma's
    "All systems connected" needs each connection's state (Shopify, Meta Ads), which the API does
    not serve.
11. **Decision wording.** A decision's options carry ids (`pause_until_restock`, `reduce_budget`) and
    raw actions (`change: "-0.3"`), not the entity's name or a formatted label: the card asks
    "Pause until restock?" where Figma asks "Pause ‘Trail Jacket — Prospecting’ until restock?", and
    says "Reduce budget" for "Cut budget 30%" (the frontend computes no percentage). Page 3 will
    need entity names and formatted option labels.
12. **Estimate method.** "simulated 1,000 times" needs the simulation count; the sheet says how in
    words from the method id ("resampled from your history"). "What could change this" is not part
    of a fact's proof; a decision's options carry `risks` and `invalidated_if`, which page 3 can
    show on the decision's estimates.
13. **"Do nothing $0".** The baseline has no fact, so no amount is shown.
14. **Formula wording.** A formula's description is an expression over metric ids
    (`contribution_after_ads − fixed_costs`); Figma's "How it's calculated" reads "Sum of daily ad
    spend, Sep 23–27". The sheet shows the API's text as it is.

### Not built yet (later pages)

15. The conversation is empty: the morning brief, the date line and answers come with page 2. The
    proof screenshots open over the `/style-guide` catalogue instead of the conversation.
16. The safety-check line of the catalogue's permission card is written from the option's
    reversibility; page 3 shows the policy's real checks (`POST /policy/preview`).
17. The estimate sheet's caveat is generic ("This is a range, not a promise. Most outcomes land
    between the low and high ends."); Figma's "I'll measure the result after the ad resumes" and
    "Back to options" belong to a decision's estimate (page 3).
18. Narrow screens (390 px) are page 9's responsive pass; the shell is laid out for desktop.

### Small visual differences

19. Status dots and range dots are CSS circles; Figma exports them as 5 px SVG dots.
20. Number buttons get a hover colour and a focus ring; Figma has no states for them.
