# ADR 0025: The web platform

- Status: accepted (page 1, Foundation; later pages extend it)
- Date: 2026-11-02

## Context

The backend is complete (API v1, ADR 0020). The web platform is the owner's main surface: a
conversation, the morning brief, decisions to approve, goals, the journal and settings (Task 7,
built one page at a time, each reviewed against the Figma file before the next). Four rules frame
it: the frontend never computes a number; every number opens its proof; an estimate is always a
range; merchant text is text, never HTML. Two more come from the product: light and dark themes,
and WCAG AA contrast in both.

## Decision

**Stack.** React 18, Vite 7, TypeScript strict (`noUncheckedIndexedAccess`,
`noPropertyAccessFromIndexSignature`), Tailwind 4 configured in CSS,
TanStack Query 5 for server state, React Router 7, no global state library. The API client is
`openapi-fetch` over types generated from `docs/api/openapi.json` (`npm run api`); `make web-lint`
fails when the generated file is stale. Figtree is self-hosted (`@fontsource/figtree`, OFL): no
request leaves for a font CDN.

**Layout of `frontend/src`.** `api/` (client, CSRF middleware, problem errors, query client),
`auth/` (session hooks, sign-in page, the session gate), `facts/` (facts, the proof sheet, the
Verified seal), `charts/` (plotting only), `decisions/`, `shell/` (rail, header, composer),
`stores/`, `theme/`, `format/`, `ui/` (the style guide's primitives), `pages/`, `dev/` (the
component catalogue, development builds only), `test/` (fakes and render helpers). A context is
created in its own module and provided by a component, so fast refresh holds.

**Design tokens.** The Figma style guide becomes CSS variables (`--pa-*`) on `:root` and
`[data-theme="dark"]`, exposed to Tailwind as semantic utilities (`bg-surface`, `text-ink-muted`,
`rounded-card`). Tailwind's default palette, type scale, radii and shadows are removed, so nothing
outside the style guide can be used by accident. Icons are the SVG files exported from Figma,
drawn as CSS masks in the current text colour: one file per icon serves both themes.

**Contrast.** Three Figma pairs fall under 4.5:1, so text gets its own tokens: blue text
`#065DE6` light and `#5A96FF` dark (was `#0866FF` on grey boxes, 4.30, and `#4C8DFF` on the
selected rail item, 4.49), the dark filled button `#1F6BFA` (white on `#4C8DFF` was 3.20), red
text `#D91A3B` light and `#FF6B7D` dark (`#E41E3F` was 4.11 and 3.89). Marks (brand mark, range
marker, dots) keep the Figma blues: they are graphics, above 3:1.

**Themes.** The system's by default, the owner's pick once toggled (kept in local storage, and
for the visit when storage is refused). The theme is applied before the first render, so a dark
system never flashes light.

**No number is made in the frontend.** The API writes every text a number is shown as: `display`
(short: whole units, a range as "low to high", a change signed) on screens, `formatted` (exact) in
the proof sheet, and an estimate's P10, P50 and P90 in both. ESLint bans `Math.round/floor/ceil/trunc`, `toFixed`,
`toPrecision`, `toLocaleString` and the `Intl` global. A number on screen is a fact's `formatted`
text. Two exceptions, each confined to one module: `src/charts/` maps API values to positions on
an axis (never shown as numbers), and `src/format/dates.ts` formats dates with `Intl` (the API
serves instants; a fact's period is half-open, so its last day is the instant before its end).
Counts and versions the API returns as integers are printed as they are.

**Every number is a button.** `FactValue` shows the formatted text and opens the proof sheet: a
modal side sheet with the fact's kind (exact, or estimate with its range and method), formula and
version, period, the facts it is built from (each one opens in turn, with Back) and its source
tables with their row counts. Focus moves into the sheet, stays there, and returns to the number.
The Verified seal on a card with numbers says that code computed them and links to the proof.

**Estimates are ranges.** `RangeBar` shows P10 and P90 as the API formatted them, at the ends of
the track, and P50 as a mark placed between them; each bar spans its own range, as in Figma.

**Sign-in.** By email link (ADR 0020): the token travels in the URL fragment and is removed from
the address bar before it is exchanged. On a demo server (the API's `GET /auth/demo` says so: only
`bench/demo_serve.py` sets `DEMO_OWNER_EMAIL`), the page first offers "Explore the demo store",
and `/demo` opens it directly: `POST /auth/demo-session` opens the demo owner's session without an
email, in any build, and answers 404 anywhere else (updated 2026-11-04; the earlier development
button read a sign-in email from Mailpit and broke past five links an hour). The component
catalogue stays behind `import.meta.env.DEV` (checked on `npm run build`). A request refused with
401 forgets the session,
and the gate sends the owner to sign in, then back to the page they were on.

**Dependencies.** `npm audit --omit=dev` is clean. The development tools carry one moderate
advisory (a `minimatch` ReDoS through ESLint and the test tooling) that never reaches the browser;
it is accepted until upstream releases, and `make web-audit` keeps it visible. Source maps are
built for error reports but not linked from the served bundles.

**Review screenshots.** `node frontend/scripts/screens.mjs` drives the browser installed on the
machine (`playwright-core`, no download) and writes light and dark screenshots of the running app
to `docs/screens/page-<n>/app/`, which sit next to the Figma frames for review.

## Consequences

- A screen can only show what the API serves. Page 1's review found gaps, reported before any
  backend change and then filled by the API (`docs/screens/page-1/README.md`): the store's name,
  short and exact texts with P10/P50/P90, decision and option labels with "do nothing", formulas in
  plain words, a source's rows with their amounts and freshness, the simulation count, a name for
  every fact. Each connection's health is still to come.
- Formatting lives in one place, the API; a currency or rounding change needs no frontend change.
- The token rules keep both themes accessible, but every new colour needs a token, not a class.
