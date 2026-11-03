import { Blob as NodeBlob } from "node:buffer";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useGoalAsk } from "@/goals/ask";
import { CAMPAIGN, DECISION, NAMES, decision } from "@/test/conversation";
import { estimateFact, exact } from "@/test/facts";
import { json, problem, sse, type FakeApi } from "@/test/fakeApi";
import { mockSystemTheme } from "@/test/matchMedia";
import { renderApp, renderInStore, signedInApi, STORE_ID } from "@/test/render";

const BASE = `/api/v1/stores/${STORE_ID}`;
const GOAL = "b18da45e-e3f6-4649-ab88-abf60b975534";
const PLAN = "92a52bc7-0d25-4eab-b3f9-ec40fb18528b";
const STEP_DECISION = "145b1a58-5bb0-4f9f-bdba-028390e39406";
const REPLACED = "10edd4fa-9e7d-4898-9643-d9f0bac8040e";
const RETARGETING = "ef059977-c250-5493-9b6f-2a67cd56629b";
const PLAN_NAMES = { ...NAMES, [`campaign:${RETARGETING}`]: "Trail Essentials — Retargeting" };

beforeEach(() => {
  mockSystemTheme(false);
});

const money = (id: number, display: string, value: string, name: string) => ({
  ...exact,
  fact_id: id,
  display,
  value,
  name,
});
const range = (
  id: number,
  raw: [string, string, string],
  shown: [string, string, string],
  name: string,
) => ({
  ...estimateFact(id, raw, shown, shown),
  name,
});
const ratio = (id: number, raw: [string, string, string], shown: string, name: string) => ({
  ...estimateFact(id, raw, [shown, shown, shown], [shown, shown, shown]),
  display: shown,
  unit: "ratio",
  name,
});

const TARGET = money(1, "$225,000", "225000.00", "Target net profit");
const FORECAST = range(
  100,
  ["167131", "224540", "276743"],
  ["$167,131", "$224,540", "$276,743"],
  "Forecast net profit",
);
const CHANCE = ratio(
  101,
  ["0.481", "0.495", "0.510"],
  "0.48× to 0.51×",
  "Chance of reaching the target",
);
const GAP = range(
  102,
  ["-51743", "0", "57869"],
  ["−$51,743", "$0", "$57,869"],
  "Gap to the target",
);

function goal(status = "planned", extra: Record<string, unknown> = {}) {
  return {
    goal_id: GOAL,
    metric: "net_profit",
    target_fact_id: 1,
    currency: "USD",
    as_of: "2026-09-01",
    deadline: "2026-11-30",
    horizon_days: 90,
    status,
    question: "I want 225,000 in net profit over the next three months.",
    created_at: "2026-11-03T00:32:50Z",
    confirmed_at: status === "draft" ? null : "2026-11-03T00:32:50Z",
    restatement:
      "Your goal: net profit of {{F1}} in total from 2026-09-01 to 2026-11-29 included, the net profit of {{E:store}} as a whole.",
    facts: { "1": TARGET },
    names: { store: "Northwind Outdoor" },
    ...extra,
  };
}

function feasibility(extra: Record<string, unknown> = {}) {
  return {
    goal_id: GOAL,
    metric: "net_profit",
    horizon_days: 90,
    verdict: "possible",
    verdict_band: ["possible", "possible"],
    probability: "0.4950",
    probability_range: ["0.4810", "0.5100"],
    probability_fact_id: 101,
    gap_fact_id: 102,
    forecast_fact_id: 100,
    checkpoints: [],
    low_evidence: ["yearly seasonality not learned"],
    facts: { "1": TARGET, "100": FORECAST, "101": CHANCE, "102": GAP },
    ...extra,
  };
}

const MILESTONES = [
  range(
    290,
    ["16438", "19300", "22297"],
    ["$16,438", "$19,300", "$22,297"],
    "Milestone net profit",
  ),
  range(
    291,
    ["33453", "38500", "43690"],
    ["$33,453", "$38,500", "$43,690"],
    "Milestone net profit",
  ),
  range(
    292,
    ["49813", "57200", "64763"],
    ["$49,813", "$57,200", "$64,763"],
    "Milestone net profit",
  ),
];

function plan(status = "accepted") {
  return {
    plan_id: PLAN,
    goal_id: GOAL,
    status,
    as_of: "2026-09-01",
    detailed_days: 90,
    payload: {
      milestones: [
        { day: 7, date: "2026-09-08", fact_id: 290 },
        { day: 14, date: "2026-09-15", fact_id: 291 },
        { day: 21, date: "2026-09-22", fact_id: 292 },
      ],
      experiments: [
        {
          lever: "price_test",
          summary:
            "Test a small price increase on {{E:product:ea63836b-e0d7-5298-b9db-b58631ed27f1}}.",
          evidence: [],
          experiment: {
            cap: "one product, at most 5% above its price",
            success: "its margin rises",
            duration_days: 14,
          },
        },
      ],
      assumptions: ["campaigns keep spending at their recent daily level"],
      target_fact_id: 1,
      outcome_fact_id: 288,
      profit_change_fact_id: 289,
      probability_with_fact_id: 287,
      probability_without_fact_id: 286,
    },
    steps: [
      {
        step_id: "s-1",
        position: 1,
        lever: "scale_profitable",
        kind: "decision",
        due_date: "2026-09-01",
        actions: [],
        summary: `Raise the daily budget of {{E:campaign:${RETARGETING}}}.`,
        evidence: [],
        effect_fact_id: 303,
        status: "proposed",
        decision_id: STEP_DECISION,
      },
      {
        step_id: "s-2",
        position: 2,
        lever: "reallocate_budget",
        kind: "decision",
        due_date: "2026-09-01",
        actions: [],
        summary: `Lower the daily budget of {{E:campaign:${CAMPAIGN}}}, which loses money.`,
        evidence: [],
        effect_fact_id: 304,
        status: "superseded",
        decision_id: REPLACED,
      },
    ],
    facts: {
      "1": TARGET,
      "286": ratio(286, ["0.48", "0.49", "0.51"], "0.48× to 0.51×", "Chance without the plan"),
      "287": ratio(287, ["0.50", "0.51", "0.53"], "0.50× to 0.53×", "Chance with the plan"),
      "288": range(
        288,
        ["169093", "226000", "279307"],
        ["$169,093", "$226,000", "$279,307"],
        "Projected net profit with the plan",
      ),
      "289": range(
        289,
        ["740", "2600", "5042"],
        ["+$740", "+$2,600", "+$5,042"],
        "Profit added by the plan",
      ),
      "290": MILESTONES[0],
      "291": MILESTONES[1],
      "292": MILESTONES[2],
      "303": range(
        303,
        ["456", "1500", "2717"],
        ["+$456", "+$1,500", "+$2,717"],
        "Profit added by this step",
      ),
      "304": range(
        304,
        ["-83", "1400", "3108"],
        ["−$83", "+$1,400", "+$3,108"],
        "Profit added by this step",
      ),
    },
    names: PLAN_NAMES,
  };
}

const ACTUAL = money(371, "$17,572", "17572.00", "Net profit");
const PROGRESS = [
  {
    progress_id: "p-1",
    plan_id: PLAN,
    kind: "weekly",
    as_of: "2026-09-08",
    day: 7,
    actual_fact_id: 371,
    milestone_fact_id: 290,
    probability_fact_id: null,
    status: "waiting_for_approval",
    verdict: "stretch",
    adherence: {},
    revision_proposed: false,
    reason: "the plan's steps due so far are waiting for your approval",
    facts: { "290": MILESTONES[0], "371": ACTUAL },
    names: {},
  },
  {
    progress_id: "p-2",
    plan_id: PLAN,
    kind: "revision",
    as_of: "2026-09-15",
    day: 14,
    actual_fact_id: null,
    milestone_fact_id: null,
    probability_fact_id: null,
    status: null,
    verdict: null,
    adherence: {},
    revision_proposed: true,
    reason: `its reallocate budget step was superseded: another pending decision acts on {{E:campaign:${CAMPAIGN}}}`,
    facts: {},
    names: { [`campaign:${CAMPAIGN}`]: NAMES[`campaign:${CAMPAIGN}`] },
  },
];

function goals(extra: (fake: FakeApi) => FakeApi = (f) => f) {
  return extra(
    signedInApi()
      .on(`GET ${BASE}/goals`, [goal()])
      .on(`GET ${BASE}/goals/${GOAL}/feasibility`, feasibility())
      .on(`GET ${BASE}/goals/${GOAL}/plans`, [plan()])
      .on(`GET ${BASE}/goals/${GOAL}/progress`, PROGRESS)
      .on(
        `GET ${BASE}/decisions/${REPLACED}`,
        decision("superseded", {
          decision_id: REPLACED,
          superseded_by: DECISION,
          superseded_reason: `another pending decision acts on {{E:campaign:${CAMPAIGN}}}`,
        }),
      )
      .on(`GET ${BASE}/decisions/${DECISION}`, decision("proposed")),
  );
}

describe("Goals", () => {
  it("shows the goal, whether it is within reach, and the plan with and without it", async () => {
    renderApp("/goals", goals().api);
    expect(await screen.findByRole("heading", { name: "Goals", level: 1 })).toBeVisible();
    const yours = await screen.findByRole("article", { name: "Your goal" });
    expect(within(yours).getByText("Following its plan")).toBeVisible();
    expect(within(yours).getByRole("button", { name: "$225,000, see the proof" })).toBeVisible();
    expect(within(yours).getByText("Northwind Outdoor")).toBeVisible();

    const reach = await screen.findByRole("region", { name: "Within reach?" });
    expect(within(reach).getAllByText("Possible")[0]).toBeVisible(); // the verdict, then its step
    const lit = reach.querySelectorAll('[data-part="verdict-band"] [data-lit="true"]');
    expect([...lit].map((step) => step.textContent)).toEqual(["Possible"]);
    expect(
      within(reach).getByRole("button", { name: "0.48× to 0.51×, see the proof" }),
    ).toBeVisible();
    expect(within(reach).getByText("Low evidence: yearly seasonality not learned.")).toBeVisible();
    expect(
      within(reach).getByRole("button", { name: /^\$167,131 to \$276,743, most likely/ }),
    ).toBeVisible();

    const thePlan = screen.getByRole("region", { name: "The plan" });
    expect(within(thePlan).getByRole("img", { name: /The plan week by week/ })).toBeVisible();
    expect(thePlan.querySelectorAll('[data-part="actual"]')).toHaveLength(1);
    expect(thePlan.querySelectorAll('[data-part="target"]')).toHaveLength(1);
    expect(within(thePlan).getByText("Target, $225,000")).toBeVisible();
    expect(within(thePlan).getAllByText("Without the plan")).toHaveLength(2);
    expect(
      within(thePlan).getByRole("button", { name: "$169,093 to $279,307, see the proof" }),
    ).toBeVisible();
    expect(
      within(thePlan).getByRole("button", { name: "0.50× to 0.53×, see the proof" }),
    ).toBeVisible();
    expect(
      within(thePlan)
        .getByText(/I propose to revise the plan/)
        .closest("p"),
    ).toHaveTextContent("another pending decision acts on Trail Jacket — Prospecting");
    expect(within(thePlan).getByText("Price test")).toBeVisible();
    expect(within(thePlan).getByText(/over 14 days/)).toBeVisible();
  });

  it("strikes the superseded step through and names what replaced it", async () => {
    renderApp("/goals", goals().api);
    const first = await screen.findByRole("listitem", { name: "Step 1" });
    expect(first).toHaveTextContent("Raise the daily budget of Trail Essentials — Retargeting.");
    expect(within(first).getByText("Waiting for you")).toBeVisible();
    expect(
      within(first).getByRole("button", { name: "+$456 to +$2,717, see the proof" }),
    ).toBeVisible();
    const second = screen.getByRole("listitem", { name: "Step 2" });
    expect(within(second).getByText("Replaced")).toBeVisible();
    expect(second.querySelector(".line-through")).toHaveTextContent("Trail Jacket — Prospecting");
    const replacement = await within(second).findByRole("button", {
      name: "Pause ‘Trail Jacket — Prospecting’ until restock",
    });
    expect(second).toHaveTextContent(
      "(another pending decision acts on Trail Jacket — Prospecting)",
    );
    await userEvent.click(replacement);
    expect(await screen.findByRole("heading", { name: "Decisions", level: 1 })).toBeVisible();
  });

  it("follows the weeks, including those waiting for the owner's approval", async () => {
    renderApp("/goals", goals().api);
    const weeks = await screen.findByRole("region", { name: "Week by week" });
    const items = within(weeks).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText("Waiting for your approval")).toBeVisible();
    expect(items[0]).toHaveTextContent("Actual $17,572");
    expect(items[0]).toHaveTextContent("Plan $16,438 to $22,297");
    expect(within(items[1]!).getByText("Revision proposed")).toBeVisible();
  });

  it("beyond 90 days shows a band, why the evidence is thin, and quarterly checkpoints", async () => {
    const far = feasibility({
      horizon_days: 365,
      verdict: null,
      probability: null,
      verdict_band: ["stretch", "possible"],
      checkpoints: [{ day: 91, date: "2026-12-01", fact_id: 100 }],
      low_evidence: ["less than a year of history"],
    });
    renderApp("/goals", goals((f) => f.on(`GET ${BASE}/goals/${GOAL}/feasibility`, far)).api);
    const reach = await screen.findByRole("region", { name: "Within reach?" });
    expect(within(reach).getByText("Between a stretch and possible")).toBeVisible();
    const band = reach.querySelectorAll('[data-part="verdict-band"] [data-lit="true"]');
    expect([...band].map((step) => step.textContent)).toEqual(["A stretch", "Possible"]);
    expect(within(reach).queryByText(/Chance of reaching it/)).toBeNull();
    expect(within(reach).getByText(/I give no single chance/)).toBeVisible();
    expect(within(reach).getByText("Low evidence: less than a year of history.")).toBeVisible();
    const checkpoints = within(reach).getByRole("region", { name: "Checkpoints" });
    expect(checkpoints).toHaveTextContent("Dec 1, 2026");
  });

  it("restates a typed goal, then confirms it", async () => {
    const fake = goals((f) =>
      f
        .on(`GET ${BASE}/goals`, [])
        .on(`GET ${BASE}/goals/${GOAL}/plans`, [])
        .on(`GET ${BASE}/goals/${GOAL}/progress`, [])
        .on(`POST ${BASE}/ask/stream`, () => {
          fake.on(`GET ${BASE}/goals`, [goal("draft")]);
          return sse(["answer", { status: "confirmation", goal_id: GOAL }]);
        })
        .on(`POST ${BASE}/goals/${GOAL}/confirm`, () => {
          fake.on(`GET ${BASE}/goals`, [goal("confirmed")]);
          return json(feasibility());
        })
        .on(`POST ${BASE}/goals/${GOAL}/plans`, plan("proposed")),
    );
    renderApp("/goals", fake.api);
    expect(await screen.findByText("No goal yet: say or type one above.")).toBeVisible();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Say or type a goal" }),
      "I want 225,000 in net profit over the next three months.{Enter}",
    );
    const sent = fake.requests.find((r) => r.url.endsWith("/ask/stream"));
    expect(await sent?.json()).toEqual({
      question: "I want 225,000 in net profit over the next three months.",
    });
    expect(await screen.findByText(/Here is your goal as I understood it/)).toBeVisible();
    const yours = await screen.findByRole("article", { name: "Your goal" });
    expect(within(yours).getByText("Waiting for your confirmation")).toBeVisible();
    await userEvent.click(within(yours).getByRole("button", { name: "Confirm this goal" }));
    expect(await screen.findByRole("region", { name: "Within reach?" })).toBeVisible();
    expect(fake.requests.some((r) => r.method === "POST" && r.url.endsWith("/confirm"))).toBe(true);
    await userEvent.click(await screen.findByRole("button", { name: "Make a plan" }));
    expect(fake.requests.some((r) => r.method === "POST" && r.url.endsWith("/plans"))).toBe(true);
  });

  it("accepts a proposed plan", async () => {
    const fake = goals((f) =>
      f
        .on(`GET ${BASE}/goals/${GOAL}/plans`, [plan("proposed")])
        .on(`POST ${BASE}/goals/${GOAL}/plans/${PLAN}/accept`, plan("accepted")),
    );
    renderApp("/goals", fake.api);
    const thePlan = await screen.findByRole("region", { name: "The plan" });
    expect(within(thePlan).getByText("Proposed: waiting for you")).toBeVisible();
    await userEvent.click(within(thePlan).getByRole("button", { name: "Accept the plan" }));
    await waitFor(() => {
      expect(fake.requests.some((r) => r.url.endsWith(`/plans/${PLAN}/accept`))).toBe(true);
    });
  });

  it("says when a question is not a goal, and when the goals cannot be read", async () => {
    const fake = goals((f) =>
      f
        .on(`GET ${BASE}/goals`, () => problem(503, "down"))
        .on(`POST ${BASE}/ask/stream`, () =>
          sse(["answer", { status: "answered", goal_id: null }]),
        ),
    );
    renderApp("/goals", fake.api);
    expect(await screen.findByText("The goals could not be loaded.")).toBeVisible();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Say or type a goal" }),
      "Why?{Enter}",
    );
    expect(await screen.findByText(/That does not read as a goal/)).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Ask other questions in the conversation" }),
    ).toBeVisible();
  });
});

function Probe() {
  const { ask, byVoice } = useGoalAsk();
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          byVoice(new NodeBlob(["voice"], { type: "audio/webm" }) as Blob);
        }}
      >
        say
      </button>
      <output>
        {ask.state === "drafted" ? `${ask.state} ${ask.goalId} ${ask.heard ?? ""}` : ask.state}
      </output>
    </div>
  );
}

describe("a goal said aloud", () => {
  // jsdom's Blob cannot travel in a fetch body: Node's FormData and Blob, as a browser sends.
  beforeEach(async () => {
    const form = await new Response("a=b", {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    }).formData();
    vi.stubGlobal("FormData", form.constructor);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the recording, shows what was heard, and drafts the goal", async () => {
    const fake = signedInApi().on(`POST ${BASE}/ask/voice`, () =>
      sse(["transcript", { transcript: "225,000 in three months" }], ["answer", { goal_id: GOAL }]),
    );
    renderInStore(<Probe />, fake.api);
    await userEvent.click(screen.getByRole("button", { name: "say" }));
    expect(await screen.findByText(`drafted ${GOAL} 225,000 in three months`)).toBeInTheDocument();
    const sent = fake.requests.find((r) => r.url.endsWith("/ask/voice"));
    expect(sent?.headers.get("content-type")).toMatch(/^multipart\/form-data/);
    expect(await sent?.text()).toContain('filename="goal.webm"');
  });

  it("fails when nothing was heard", async () => {
    const fake = signedInApi().on(`POST ${BASE}/ask/voice`, () => sse(["no_speech", {}]));
    renderInStore(<Probe />, fake.api);
    await userEvent.click(screen.getByRole("button", { name: "say" }));
    expect(await screen.findByText("failed")).toBeInTheDocument();
  });
});
