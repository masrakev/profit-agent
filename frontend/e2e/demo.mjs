/**
 * The demo script, end to end, in a real browser on a fresh demo seed (`make e2e`).
 *
 * Starts its own API (the demo store's recorded model exchanges at their recorded pace), the
 * executor and the dev server; drives the browser installed on the machine (Edge by default,
 * E2E_BROWSER=chrome for Chrome) through the demo; stops them. Needs `make up` (Postgres,
 * Mailpit) and ports 8000 and 3000 free. E2E_SHOTS=<dir> also writes the live Working block at
 * 1440 px, dark and light, there. Exits 0 when every step held, 1 otherwise.
 *
 *   1. The morning brief opens the conversation.
 *   2. A typed question: the Working block streams, then the answer with its evidence and the
 *      Verified seal.
 *   3. The status line leads to Decisions; Review opens the approval card; Approve; executing;
 *      executed, with the platform's confirmation.
 *   4. The Journal records it.
 *   5. Goals: the 90-day goal and its plan; the six-month goal with low evidence and quarterly
 *      checkpoints.
 */
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const WEB = "http://localhost:3000";
const API = "http://127.0.0.1:8000";
const QUESTION = "What is hurting my profit the most this week, and what should I do about it?";
const SHOTS = process.env.E2E_SHOTS ? path.resolve(process.env.E2E_SHOTS) : null;

const children = [];

function start(name, command, args, cwd) {
  const child = spawn(command, args, { cwd, shell: true, stdio: ["ignore", "pipe", "pipe"] });
  child.output = "";
  child.stdout.on("data", (chunk) => (child.output += chunk));
  child.stderr.on("data", (chunk) => (child.output += chunk));
  child.label = name;
  children.push(child);
  return child;
}

function stopAll() {
  for (const child of children) {
    if (child.exitCode !== null) continue;
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore" });
    } else {
      child.kill("SIGTERM");
    }
  }
}

async function free(url) {
  try {
    await fetch(url, { signal: AbortSignal.timeout(1500) });
    return false;
  } catch {
    return true;
  }
}

async function ready(url, label, seconds = 90) {
  const until = Date.now() + seconds * 1000;
  while (Date.now() < until) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (response.ok) return;
    } catch {
      // not yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${label} did not start`);
}

let step = "starting";
const passed = [];
function holds(what) {
  passed.push(what);
  console.log(`  ok  ${what}`);
}

let browser;
try {
  if (!(await free(`${API}/api/v1/ready`)) || !(await free(WEB))) {
    throw new Error("ports 8000 and 3000 must be free: stop the API and the dev server first");
  }
  start("api", "uv", ["run", "python", "-m", "bench.demo_serve", "api"], ROOT);
  start("worker", "uv", ["run", "python", "-m", "bench.demo_serve", "worker"], ROOT);
  start(
    "web",
    "npm",
    ["run", "dev", "--", "--port", "3000", "--strictPort"],
    path.join(ROOT, "frontend"),
  );
  await ready(`${API}/api/v1/ready`, "the API");
  await ready(WEB, "the dev server");

  browser = await chromium.launch({ channel: process.env.E2E_BROWSER ?? "msedge" });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const problems = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().includes("401")) problems.push(m.text());
  });

  step = "sign in";
  await page.goto(`${WEB}/sign-in`);
  await page.getByRole("button", { name: "Use the demo store" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/sign-in"), { timeout: 60_000 });

  step = "the morning brief";
  const brief = page.getByRole("article", { name: "Morning brief" });
  await brief.waitFor({ timeout: 30_000 });
  await brief.getByRole("heading", { level: 1 }).waitFor();
  holds("the morning brief opens the conversation");

  step = "a typed question";
  await page.getByRole("textbox", { name: "Ask anything about your store" }).fill(QUESTION);
  await page.keyboard.press("Enter");
  const working = page.getByRole("region", { name: "Working" });
  await working.getByRole("listitem").nth(1).waitFor({ timeout: 60_000 });
  await page.locator('.agent-mark[data-state="working"]').first().waitFor();
  holds("the Working block streams the agent's steps, its mark breathing");
  if (SHOTS) {
    await mkdir(SHOTS, { recursive: true });
    await working.scrollIntoViewIfNeeded();
    for (const scheme of ["dark", "light"]) {
      await page.evaluate((s) => {
        localStorage.setItem("profit-agent.theme", s);
        document.documentElement.dataset.theme = s;
        document.documentElement.style.colorScheme = s;
      }, scheme);
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(SHOTS, `ask-working-1440-${scheme}.png`) });
    }
  }
  const answer = page.getByRole("article", { name: "Answer" });
  await answer.waitFor({ timeout: 240_000 });
  await answer.getByRole("region", { name: "Evidence" }).waitFor();
  await answer.getByRole("button", { name: "Verified", exact: true }).click();
  await answer.getByRole("button", { name: "See the proof", exact: true }).waitFor();
  holds("the answer, with its evidence and the Verified seal");

  step = "Decisions";
  await page.getByRole("link", { name: "Waiting for your decision" }).click();
  await page.getByRole("heading", { name: "Decisions", level: 1 }).waitFor();
  const waiting = page.getByRole("region", { name: "Waiting for you" });
  const pause = waiting.getByRole("listitem").filter({ hasText: /Pause ‘Trail Jacket/ });
  await pause.getByRole("button", { name: "Review" }).click();
  const approve = pause.getByRole("button", { name: "Approve" });
  await approve.waitFor();
  await pause.getByText(/^Safety checks passed/).waitFor();
  holds("Review opens the approval card on the Decisions page");

  step = "Approve";
  await approve.click();
  await page
    .getByRole("status")
    .filter({ hasText: /Approved: starting|Carrying it out/ })
    .first()
    .waitFor({ timeout: 30_000 });
  holds("approved: it is being carried out");
  await page
    .getByText(/reports the campaign paused/)
    .first()
    .waitFor({ timeout: 90_000 });
  holds("executed, with the platform's confirmation");

  step = "the Journal";
  await page.getByRole("link", { name: "Journal" }).click();
  await page.getByRole("heading", { name: "Journal", level: 1 }).waitFor();
  await page
    .getByText(/^Carried out: Pause ‘Trail Jacket/)
    .first()
    .waitFor({ timeout: 30_000 });
  await page
    .getByText(/You approved in the app: Pause ‘Trail Jacket/)
    .first()
    .waitFor();
  holds("the Journal records the approval and what was carried out");

  step = "Goals";
  await page.getByRole("link", { name: "Goals" }).click();
  const goal = page.getByRole("article", { name: "Your goal" });
  await goal.getByText("Following its plan").waitFor({ timeout: 30_000 });
  await goal.getByText(/over the next three months/).waitFor();
  const reach = page.getByRole("region", { name: "Within reach?" });
  await reach.getByText(/Chance of reaching it/).waitFor();
  await reach
    .locator("button[data-fact]")
    .filter({ hasText: /^\d+( to \d+)?%/ })
    .first()
    .waitFor();
  await page.getByRole("region", { name: "The plan" }).getByRole("img").waitFor();
  holds("the 90-day goal: within reach as a percentage, and its plan");
  const others = page.getByRole("region", { name: "Other goals" });
  await others
    .getByRole("listitem")
    .filter({ hasText: /2027/ })
    .getByRole("button", { name: "Show" })
    .click();
  const far = page.getByRole("region", { name: "Within reach?" });
  await far.getByText(/I give no single chance/).waitFor({ timeout: 30_000 });
  await far.getByText(/^Low evidence:/).waitFor();
  await far.getByRole("region", { name: "Checkpoints" }).waitFor();
  holds("the six-month goal: a band, low evidence and quarterly checkpoints");

  if (problems.length > 0) throw new Error(`console errors: ${problems.join(" | ")}`);
  step = "done";
  console.log(`\nThe demo script holds: ${String(passed.length)} steps.`);
} catch (error) {
  console.error(`\nFAILED at "${step}": ${error instanceof Error ? error.message : String(error)}`);
  for (const child of children) {
    if (child.output) console.error(`--- ${child.label}\n${child.output.slice(-2000)}`);
  }
  process.exitCode = 1;
} finally {
  await browser?.close();
  stopAll();
}
