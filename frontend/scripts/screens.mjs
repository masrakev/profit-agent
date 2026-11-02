/**
 * Screenshots of the running app, light and dark, for the review of a page (Task 7: saved under
 * docs/screens/ next to the Figma frames). Drives the browser installed on the machine (Edge by
 * default, SCREENS_BROWSER=chrome for Chrome): nothing is downloaded.
 *
 *   make web                       # the dev server, with the API on the demo store and Mailpit up
 *   node scripts/screens.mjs       # writes docs/screens/page-1/app/<screen>-<light|dark>.png
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const BASE = process.env.SCREENS_BASE_URL ?? "http://localhost:3000";
const OUT = new URL("../../docs/screens/page-1/app/", import.meta.url);
const VIEWPORT = { width: 1280, height: 960 };
// The demo session is kept between runs (the API sends 5 sign-in links an hour at most).
const SESSION = new URL("../node_modules/.cache/screens-session.json", import.meta.url);

async function settle(page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForLoadState("networkidle");
}

/** The demo owner's session: the last run's while it is valid, else a new one. */
async function demoSession(browser) {
  try {
    const saved = JSON.parse(await readFile(SESSION, "utf8"));
    const context = await browser.newContext({ viewport: VIEWPORT, storageState: saved });
    const response = await context.request.get(`${BASE}/api/v1/auth/session`);
    await context.close();
    if (response.ok()) return saved;
  } catch {
    // no saved session, or it cannot be read: sign in
  }
  const state = await signIn(browser);
  await mkdir(new URL(".", SESSION), { recursive: true });
  await writeFile(SESSION, JSON.stringify(state));
  return state;
}

/** Signs in as the demo owner, through the development build's button. */
async function signIn(browser) {
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();
  await page.goto(`${BASE}/sign-in`);
  await page.getByRole("button", { name: "Use the demo store" }).click();
  await page.waitForURL(`${BASE}/`);
  const state = await context.storageState();
  await context.close();
  return state;
}

async function capture(browser, session, scheme) {
  const file = (name) => fileURLToPath(new URL(`${name}-${scheme}.png`, OUT));

  const visitor = await browser.newContext({ viewport: VIEWPORT, colorScheme: scheme });
  const signIn = await visitor.newPage();
  await signIn.goto(`${BASE}/sign-in`);
  await settle(signIn);
  await signIn.screenshot({ path: file("sign-in") });
  await visitor.close();

  const owner = await browser.newContext({
    viewport: VIEWPORT,
    colorScheme: scheme,
    storageState: session,
  });
  const page = await owner.newPage();
  await page.goto(`${BASE}/`);
  await page.getByText("Connected", { exact: true }).waitFor();
  await settle(page);
  await page.screenshot({ path: file("shell") });

  await page.goto(`${BASE}/style-guide`);
  const card = page.getByRole("article");
  await card.waitFor();
  await settle(page);
  await page.screenshot({ path: file("style-guide"), fullPage: true });
  await card.screenshot({ path: file("permission-card") });

  const loaded = (dialog) => dialog.locator('[aria-busy="true"]').waitFor({ state: "detached" });
  await page.locator("button[data-fact]").first().click();
  await loaded(page.getByRole("dialog"));
  await settle(page);
  await page.screenshot({ path: file("exact-proof") });
  await page.keyboard.press("Escape");

  await page.locator('button[aria-label$="see the proof"]').first().click();
  await loaded(page.getByRole("dialog"));
  await settle(page);
  await page.screenshot({ path: file("estimate-proof") });
  await owner.close();
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ channel: process.env.SCREENS_BROWSER ?? "msedge" });
try {
  const session = await demoSession(browser);
  for (const scheme of ["light", "dark"]) await capture(browser, session, scheme);
} finally {
  await browser.close();
}
console.log(`screens written to ${fileURLToPath(OUT)}`);
