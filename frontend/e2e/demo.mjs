/**
 * The demo script, end to end, in a real browser on a fresh demo seed (`make e2e`).
 *
 * Starts its own API (the demo store's recorded model exchanges at their recorded pace), the
 * executor and the dev server; drives the browser installed on the machine (Edge by default,
 * E2E_BROWSER=chrome for Chrome) through the demo; stops them. Needs `make up` (Postgres,
 * Mailpit) and ports 8000 and 3000 free. E2E_SHOTS=<dir> also writes the live Working block at
 * 1440 px, dark and light, there. Exits 0 when every step held, 1 otherwise.
 *
 *   1. Home opens on the morning brief.
 *   2. A question typed on Home opens Conversations: the Working block streams, then the answer
 *      with its evidence and the Verified seal.
 *   3. The status line leads to the decisions inbox; the decision opens at its address, why and
 *      then the approval card; Approve; executing; executed, with the platform's confirmation.
 *   4. The Journal (from Settings) records it.
 *   5. Goals: the 90-day goal, its plan and its thread; the six-month goal with low evidence and
 *      quarterly checkpoints ahead.
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
  holds("Home opens on the morning brief");

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
  // The recorded answer, not the fallback the API gives when no model answer is at hand.
  await answer.getByText(/^Next step:/).waitFor();
  if ((await answer.textContent())?.includes("model unavailable")) {
    throw new Error("the answer is the fallback: its model exchange was not replayed");
  }
  await answer.getByRole("button", { name: "Verified", exact: true }).click();
  await answer.getByRole("button", { name: "See the proof", exact: true }).waitFor();
  holds("the answer, with its evidence and the Verified seal");

  step = "Decisions";
  await page.getByRole("link", { name: "Waiting for your decision" }).click();
  await page.getByRole("heading", { name: "Decisions", level: 1 }).waitFor();
  const waiting = page.getByRole("list", { name: "To decide" });
  await waiting.getByRole("link", { name: /Pause ‘Trail Jacket/ }).click();
  await page.waitForURL(/\/decisions\/[0-9a-f-]{36}$/);
  const pause = page.getByRole("region", { name: /^Pause ‘Trail Jacket/ });
  await pause.getByRole("region", { name: "Why" }).waitFor();
  const approve = pause.getByRole("button", { name: "Approve" });
  await approve.waitFor();
  await pause.getByText(/^Safety checks passed/).waitFor();
  holds("the inbox opens the decision at its address: why, then the approval card");

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
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("link", { name: "Open the journal" }).click();
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
  await page
    .getByRole("region", { name: "So far" })
    .getByRole("listitem", { name: /Weekly check$/ })
    .first()
    .waitFor();
  holds("the 90-day goal: within reach as a percentage, its plan and its thread");
  const others = page.getByRole("region", { name: "Other goals" });
  await others
    .getByRole("listitem")
    .filter({ hasText: /2027/ })
    .getByRole("link", { name: "Show" })
    .click();
  await page.waitForURL(/\/goals\/[0-9a-f-]{36}$/);
  const far = page.getByRole("region", { name: "Within reach?" });
  await far.getByText(/I give no single chance/).waitFor({ timeout: 30_000 });
  await far.getByText(/^Low evidence:/).waitFor();
  const ahead = page.getByRole("region", { name: "Ahead" });
  await ahead
    .getByRole("listitem", { name: /Checkpoint$/ })
    .first()
    .waitFor();
  await ahead.getByText("Low evidence").first().waitFor();
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
