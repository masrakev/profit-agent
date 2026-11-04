/**
 * Every page and state of the app at 1440 and 390 px, light and dark, for a design review
 * (before and after a design pass). Same setup as screens.mjs: the dev server, the API on a fresh
 * demo store (`make demo-seed`), the browser installed on the machine.
 *
 *   node scripts/design-shots.mjs ../tasks/design/before
 *
 * It approves the demo's Trail Jacket pause and asks one spoken question: re-seed afterwards.
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium } from "playwright-core";

const BASE = process.env.SCREENS_BASE_URL ?? "http://localhost:3000";
const OUT = path.resolve(process.argv[2] ?? "../tasks/design/shots");
const ONLY = process.argv[3]; // a part's name, to retake one part
const WIDTHS = [1440, 390];
const SESSION = new URL("../node_modules/.cache/screens-session.json", import.meta.url);
const SPEECH = fileURLToPath(
  new URL("../../backend/tests/fixtures/voice/question_en.wav", import.meta.url),
);

async function settle(page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function session(browser) {
  try {
    const saved = JSON.parse(await readFile(SESSION, "utf8"));
    const context = await browser.newContext({ storageState: saved });
    const ok = (await context.request.get(`${BASE}/api/v1/auth/session`)).ok();
    await context.close();
    if (ok) return saved;
  } catch {
    // sign in below
  }
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${BASE}/demo`); // the demo server opens its store, without an email
  await page.waitForURL((u) => u.pathname === "/");
  const state = await context.storageState();
  await context.close();
  await mkdir(new URL(".", SESSION), { recursive: true });
  await writeFile(SESSION, JSON.stringify(state));
  return state;
}

/** The page as it is now, at every width and in both themes, whole. */
async function shoot(page, name, { quick = false, whole = true } = {}) {
  const size = page.viewportSize();
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    for (const scheme of ["dark", "light"]) {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      // The app opens light; the owner's pick (kept in local storage) sets the theme.
      await page.evaluate((s) => {
        localStorage.setItem("profit-agent.theme", s);
        document.documentElement.dataset.theme = s;
        document.documentElement.style.colorScheme = s;
      }, scheme);
      if (!quick) await settle(page);
      await page.waitForTimeout(350);
      await page.screenshot({
        path: path.join(OUT, `${name}-${String(width)}-${scheme}.png`),
        fullPage: whole,
      });
    }
  }
  if (size) await page.setViewportSize(size);
}

const browser = await chromium.launch({
  channel: process.env.SCREENS_BROWSER ?? "msedge",
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${SPEECH}%noloop`,
  ],
});
await mkdir(OUT, { recursive: true });
const state = await session(browser);
const part = (name) => !ONLY || ONLY === name;

try {
  if (part("visitor")) {
    const visitor = await browser.newContext();
    const page = await visitor.newPage();
    await page.goto(`${BASE}/sign-in`);
    await shoot(page, "sign-in");
    await visitor.close();
  }

  const owner = await browser.newContext({
    storageState: state,
    permissions: ["microphone"],
    viewport: { width: 1440, height: 900 },
  });
  const page = await owner.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning")
      console.log(`console ${m.type()}:`, m.text());
  });

  if (part("ask")) {
    // A typed question, asked first: its recorded exchange is the fresh store's (the pages below
    // compute facts of their own, which would change the question's prompt).
    await page.goto(`${BASE}/`);
    await page.getByRole("article", { name: "Morning brief" }).waitFor();
    await page
      .getByRole("textbox", { name: "Ask anything about your store" })
      .fill("What is hurting my profit the most this week, and what should I do about it?");
    await page.keyboard.press("Enter");
    // At the recorded pace (`make demo-api`) the work streams; replayed at once, it is gone.
    const working = page.getByRole("region", { name: "Working" });
    const live = await working
      .getByRole("listitem")
      .nth(1)
      .waitFor({ timeout: 60_000 })
      .then(() => true)
      .catch(() => false);
    if (live) await shoot(page, "ask-working", { quick: true });
    await page.getByRole("article", { name: "Answer" }).waitFor({ timeout: 240_000 });
    await settle(page);
    await shoot(page, "ask-answer");
  }
  if (part("pages")) {
    for (const [route, name, heading] of [
      ["/decisions", "decisions", "Decisions"],
      ["/goals", "goals", "Goals"],
      ["/journal", "journal", "Journal"],
      ["/settings", "settings", "Settings"],
    ]) {
      await page.goto(`${BASE}${route}`);
      await page.getByRole("heading", { name: heading, level: 1 }).waitFor();
      await page
        .locator('[aria-busy="true"]')
        .first()
        .waitFor({ state: "detached" })
        .catch(() => {});
      await settle(page);
      await shoot(page, name);
    }
  }

  if (part("pages")) {
    // A measured decision, read in full in the inbox.
    await page.goto(`${BASE}/decisions`);
    await page.getByRole("group", { name: "Show" }).getByRole("button", { name: "Done" }).click();
    await page.getByRole("list", { name: "Done" }).getByRole("link").last().click();
    await page.getByRole("region", { name: "What it earned" }).waitFor();
    await settle(page);
    await shoot(page, "decision-measured");
  }

  if (part("states")) {
    // Loading: the API holds its answers; empty: the store has nothing yet.
    await page.route("**/api/v1/stores/*/decisions?*", () => {});
    await page.goto(`${BASE}/decisions`);
    await page.getByRole("heading", { name: "Decisions", level: 1 }).waitFor();
    await shoot(page, "decisions-loading", { quick: true });
    await page.unroute("**/api/v1/stores/*/decisions?*");
    await page.route("**/api/v1/stores/*/decisions?*", (r) =>
      r.fulfill({ json: { items: [], next_cursor: null } }),
    );
    await page.route("**/api/v1/stores/*/trust", (r) => r.fulfill({ json: [] }));
    await page.goto(`${BASE}/decisions`);
    await page.getByText(/No decision/).waitFor();
    await shoot(page, "decisions-empty");
    await page.unrouteAll();
    await page.route("**/api/v1/stores/*/goals", (r) => r.fulfill({ json: [] }));
    await page.goto(`${BASE}/goals`);
    await page.getByText(/No goal yet/).waitFor();
    await shoot(page, "goals-empty");
    await page.unrouteAll();
  }

  if (part("conversation")) {
    await page.goto(`${BASE}/`);
    const brief = page.getByRole("article", { name: "Morning brief" });
    await brief.waitFor();
    await settle(page);
    await shoot(page, "chat");

    await brief.getByRole("button", { name: "What I checked" }).first().click();
    const checked = page.getByRole("region", { name: "What I checked" });
    await checked.getByRole("button", { name: "Full report" }).waitFor();
    await settle(page);
    await shoot(page, "chat-investigation");

    await checked.getByRole("button", { name: "See options" }).click();
    // A decision opens on the Decisions page (before the design pass: in the conversation).
    const card = page
      .getByRole("article")
      .filter({ hasText: /Safety checks passed/ })
      .filter({ has: page.getByRole("button", { name: "Approve" }) })
      .last();
    await card.getByRole("button", { name: "Approve" }).waitFor();
    await settle(page);
    await shoot(page, "chat-decision");

    // The keyboard path: focus reaches Approve, with its ring.
    await card.getByRole("button", { name: "Approve" }).focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await shoot(page, "approval-focus", { whole: false });

    await page.keyboard.press("Enter");
    await page
      .getByRole("status")
      .filter({ hasText: /Approved|Carrying/ })
      .first()
      .waitFor();
    await shoot(page, "approval-executing", { quick: true });
    await page
      .getByText(/reports the campaign|carried it out/)
      .first()
      .waitFor({ timeout: 60_000 });
    await settle(page);
    await shoot(page, "approval-executed");
  }

  await owner.close();
} finally {
  await browser.close();
}
console.log(`written to ${OUT}`);
