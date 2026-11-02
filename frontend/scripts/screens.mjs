/**
 * Screenshots of the running app, light and dark, for the review of a page (Task 7: saved under
 * docs/screens/ next to the Figma frames). Drives the browser installed on the machine (Edge by
 * default, SCREENS_BROWSER=chrome for Chrome): nothing is downloaded.
 *
 *   make web                       # the dev server, with the API on the demo store and Mailpit up
 *   node scripts/screens.mjs       # writes docs/screens/page-1/app/<screen>-<light|dark>.png
 *   node scripts/screens.mjs 2-3   # the conversation and the approval page: page-2-3/app/
 *
 * Pages 2 and 3 approve two of the demo store's decisions (the simulator carries them out) and ask
 * one spoken question (model calls): re-seed the demo store afterwards (`make demo-seed`). The
 * API needs APPROVAL_LINK_SECRET for the email links, and ffmpeg for the recording. With
 * SCREENS_EXPIRED_LINK set to an expired link's token, the expired link's page is taken too.
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const BASE = process.env.SCREENS_BASE_URL ?? "http://localhost:3000";
const PAGE = process.argv[2] ?? "1";
const OUT = new URL(`../../docs/screens/page-${PAGE}/app/`, import.meta.url);
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

/** Page 1: the sign-in page, the shell, the style guide and the proof sheets, in one theme. */
async function foundation(browser, session, scheme) {
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
  // As in Figma, a base fact with its rows: net profit, then down its lineage to the ad spend.
  const parent = async (label) => {
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("listitem").filter({ hasText: label }).getByRole("button").click();
    await loaded(page.getByRole("dialog"));
  };
  await page.locator("button[data-fact]").first().click();
  await loaded(page.getByRole("dialog"));
  await parent("Contribution after ads");
  await parent(/^Ad spend/);
  await page.getByRole("dialog").getByText("Data up to", { exact: false }).waitFor();
  await settle(page);
  await page.screenshot({ path: file("exact-proof") });
  await page.keyboard.press("Escape");

  await page.locator('button[aria-label$="see the proof"]').first().click();
  await loaded(page.getByRole("dialog"));
  await settle(page);
  await page.screenshot({ path: file("estimate-proof") });
  await owner.close();
}

/** A spoken question, played by the browser's fake microphone (the voice tests' recording). */
const SPEECH = fileURLToPath(
  new URL("../../backend/tests/fixtures/voice/question_en.wav", import.meta.url),
);
const SPEECH_SECONDS = 10.5; // the recording lasts 10.1 s

/** The same moment in both themes: the app follows the system's. */
async function both(page, name, target = page, { quick = false, ...options } = {}) {
  for (const scheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: scheme });
    if (!quick) await settle(page);
    await page.waitForTimeout(400); // the colours' transitions
    const path = fileURLToPath(new URL(`${name}-${scheme}.png`, OUT));
    await target.screenshot({ path, ...options });
  }
}

/** The message at the top of the window, clear of the composer below. */
async function into(locator) {
  await locator.page().waitForTimeout(800); // the conversation's own smooth scroll
  await locator.evaluate((element) => {
    window.scrollTo({ top: element.getBoundingClientRect().top + window.scrollY - 24 });
  });
}

/** The end of the conversation, as it reads after a new message. */
async function end(page) {
  await page.waitForTimeout(800);
  await page.evaluate(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight });
  });
}

/** The whole page at once: a window as tall as the page. */
async function whole(page, name) {
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.setViewportSize({ width: VIEWPORT.width, height });
  await both(page, name);
  await page.setViewportSize(VIEWPORT);
}

/** Pages 2 and 3: the brief, an investigation, a decision, Ask by voice, the email page. */
async function conversation(browser, session) {
  const owner = await browser.newContext({
    viewport: VIEWPORT,
    storageState: session,
    permissions: ["microphone"],
  });
  const api = async (method, path, data) => {
    const csrf = (await owner.cookies()).find((cookie) => cookie.name === "pa_csrf");
    const response = await owner.request.fetch(`${BASE}/api/v1${path}`, {
      method,
      data,
      headers: { "X-CSRF-Token": csrf?.value ?? "" },
    });
    if (!response.ok()) throw new Error(`${method} ${path}: ${response.status()}`);
    return response.json();
  };
  const [store] = (await api("GET", "/auth/session")).store_ids;
  const { items } = await api("GET", `/stores/${store}/decisions?limit=50`);
  // The demo's story: a decision replaced by the Trail Jacket's, and one more waiting.
  const replaced = items.find((d) => d.status === "superseded" && d.superseded_by);
  const story = items.find((d) => d.decision_id === replaced?.superseded_by);
  const other = items.find((d) => d.status === "proposed" && d !== story);
  if (story?.status !== "proposed" || !other) {
    throw new Error("the demo's decisions were decided already: run make demo-seed");
  }
  const link = async (d) => {
    const path = `/stores/${store}/decisions/${d.decision_id}/links`;
    return (await api("POST", path, { option_id: d.recommended_option_id })).token;
  };

  const page = await owner.newPage();
  await page.goto(`${BASE}/`);
  const brief = page.getByRole("article", { name: "Morning brief" });
  await brief.waitFor();
  await settle(page);
  await whole(page, "chat-brief");

  await brief.getByRole("button", { name: "What I checked" }).first().click();
  const checked = page.getByRole("region", { name: "What I checked" });
  await checked.getByRole("button", { name: "Full report" }).waitFor();
  await into(checked);
  await both(page, "chat-investigation");

  await checked.getByRole("button", { name: "See options" }).click();
  const card = page.getByRole("article", { name: story.label });
  await card.getByText(/^Safety checks passed/).waitFor();
  await into(card);
  await both(page, "chat-decision");
  await both(page, "decision-card", card);

  // The email approval page, as the owner's mailbox opens it: no session.
  const visitor = await browser.newContext({ viewport: VIEWPORT });
  const mail = await visitor.newPage();
  const open = async (token) => {
    await mail.goto("about:blank"); // each link as a new visit
    await mail.goto(`${BASE}/approve#token=${token}`);
    await mail.locator("main h1").first().waitFor();
  };
  const storyLink = await link(story);
  await open(storyLink);
  await both(mail, "approval-preview");
  await open(await link(replaced));
  await both(mail, "approval-replaced");
  if (process.env.SCREENS_EXPIRED_LINK) {
    await open(process.env.SCREENS_EXPIRED_LINK);
    await both(mail, "approval-expired");
  }
  const otherLink = await link(other);
  await open(otherLink);
  await mail.getByRole("button", { name: "Approve" }).click();
  await mail.getByRole("heading", { name: "Approved" }).waitFor();
  await both(mail, "approval-approved");
  await open(otherLink);
  await both(mail, "approval-used");

  // Approved in the conversation: followed live until the platform's state is read back. Before
  // the question below: answering it can propose a fresher decision that replaces this one.
  await into(card);
  await card.getByRole("button", { name: "Approve" }).click();
  const outcome = page.getByRole("article", { name: story.label });
  await outcome
    .getByRole("status")
    .filter({ hasText: /Approved|Carrying/ })
    .waitFor();
  await both(page, "decision-executing", page, { quick: true });
  await outcome.getByRole("listitem").first().waitFor({ timeout: 60_000 });
  await into(outcome);
  await both(page, "decision-executed");
  await open(storyLink);
  await both(mail, "approval-decided");

  // Asked by voice: the waveform while it records, what was heard with the work as it streams,
  // then the answer.
  await page.getByRole("button", { name: "Ask by voice" }).click();
  await page.getByRole("group", { name: "Recording your question" }).waitFor();
  const started = Date.now();
  await page.waitForTimeout(2500);
  await both(page, "voice-recording", page, { quick: true });
  await page.waitForTimeout(Math.max(0, SPEECH_SECONDS * 1000 - (Date.now() - started)));
  await page.getByRole("button", { name: "Send" }).click();
  const listening = page.getByText("Listening to your question…");
  await listening.waitFor();
  await listening.waitFor({ state: "detached", timeout: 60_000 });
  const working = page.getByRole("region", { name: "Working" });
  await working.getByRole("listitem").nth(2).waitFor({ timeout: 60_000 }); // a few steps in
  await end(page);
  await both(page, "ask-working", page, { quick: true });
  await page.getByRole("article", { name: "Answer" }).waitFor({ timeout: 180_000 });
  await end(page);
  await both(page, "ask-answer");
  await visitor.close();
  await owner.close();
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({
  channel: process.env.SCREENS_BROWSER ?? "msedge",
  // Pages 2 and 3: the microphone is the recording of a spoken question, allowed without a prompt.
  args:
    PAGE === "1"
      ? []
      : [
          "--use-fake-ui-for-media-stream",
          "--use-fake-device-for-media-stream",
          `--use-file-for-fake-audio-capture=${SPEECH}%noloop`,
        ],
});
try {
  const session = await demoSession(browser);
  if (PAGE === "1") {
    for (const scheme of ["light", "dark"]) await foundation(browser, session, scheme);
  } else {
    await conversation(browser, session);
  }
} finally {
  await browser.close();
}
console.log(`screens written to ${fileURLToPath(OUT)}`);
