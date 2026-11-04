# Page 1 — Foundation: screens next to Figma

Each sheet puts the app (left; light on top, dark below) next to the matching Figma frame (right).
The app runs on the demo store (`make demo-up`), opened at `/demo`; the
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
   store's, from the API; none is copied from Figma.
4. **Lineage in the proof (rule 2).** The proof sheet adds the formula's id and version, the
   period, and "Built from" (the parent facts, each one clickable, with Back).
5. **No invented links or sample data.** The email field starts empty (Figma shows a sample
   address). The sign-in page drops "By continuing, you agree to our Terms and Privacy
   Policy" and the footer's "Privacy" and "Help": those pages do not exist yet. The footer shows the
   product name.
6. **The sidebar (the owner's request after page 1).** Figma's 88 px rail, with labels under the
   icons, is replaced by a sidebar that works like ChatGPT's: expanded (260 px) each destination is
   an icon and its label in a 36 px row; collapsed (52 px) only the icons, naming themselves on
   hover; a button at the top switches, and the choice is remembered. The theme and the store are
   rows at its foot.
7. **Demo servers only:** "Explore the demo store" above the sign-in form; **development build
   only:** the `/style-guide` catalogue itself (absent from a production build).

### Filled by the API (the backend task after page 1)

The first review found gaps in the API; they are filled, and the screens refreshed:

- the store's name (`GET /stores/{id}`): "Northwind Outdoor · Demo store" and "NO" in the shell;
- the demo store's names: Northwind Outdoor, its Trail Jacket and "Trail Jacket — Prospecting";
- short texts for screens ("+$613 to +$654"), the exact ones for the proof, P10/P50/P90 formatted:
  the range bars label the most likely value;
- decision and option labels naming what they act on, and "Do nothing" with its zero fact ("$0");
- formulas and fact families explained in plain words, with the technical expression beneath;
- each source's rows with their date, campaign or product, and amount, "Data up to", the total;
- the estimates' simulation count ("simulated 1,000 times by the store twin");
- a name for every fact ("Change in net profit"), for the proof's title.

### Still different

8. **Connection health.** The header pill says "Connected" from the API's readiness check; Figma's
   "All systems connected" needs each connection's state (Shopify, Meta Ads), which the API does
   not serve (not part of the backend task).
9. **The proof of a campaign's number.** Figma's exact proof is the ad spend of one campaign over
   5 days ("Ad spend, Trail Jacket — Prospecting", 5 rows); the screenshot walks the store's
   lineage to the store-wide ad spend (28 rows, each naming its campaign, 10 at a time). The title
   names the metric; the fact's campaign is not in it. Figma's "Open source in Meta ↗" has no
   counterpart: the API has no link to the platform.
10. **Formatting.** The API writes "+$613 to +$654" where Figma writes "+$570 to +$614" (other
   numbers, same form), and exact texts keep their cents ("$1,489.82"). Exact texts are unsigned;
   short texts carry the sign of a change.
11. **The permission card's options.** The demo decision has three options and "Do nothing": the
    third, "Prepare a reorder of Trail Jacket", has no range (it prepares, it does not act). Figma
    shows two options with ranges.

### Not built yet (later pages)

12. The conversation is empty: the morning brief, the date line and answers come with page 2. The
    proof screenshots open over the `/style-guide` catalogue instead of the conversation.
13. The safety-check line of the catalogue's permission card is written from the option's
    reversibility; page 3 shows the policy's real checks (`POST /policy/preview`).
14. The estimate sheet's caveat is generic ("This is a range, not a promise. Most outcomes land
    between the low and high ends."); Figma's "I'll measure the result after the ad resumes" and
    "Back to options" belong to a decision's estimate (page 3).
15. Narrow screens (390 px) are page 9's responsive pass; the shell is laid out for desktop.

### Small visual differences

16. Status dots and range dots are CSS circles; Figma exports them as 5 px SVG dots.
17. Number buttons get a hover colour and a focus ring; Figma has no states for them.
