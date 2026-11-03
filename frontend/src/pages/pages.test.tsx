import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  BRIEFING,
  CAMPAIGN,
  DECISION,
  INCIDENT,
  PRODUCT,
  NAMES,
  decision,
  impact,
  option,
  zero,
} from "@/test/conversation";
import { estimateFact, exact } from "@/test/facts";
import { json, problem, type FakeApi } from "@/test/fakeApi";
import { mockSystemTheme } from "@/test/matchMedia";
import { renderApp, signedInApi, STORE_ID } from "@/test/render";

const BASE = `/api/v1/stores/${STORE_ID}`;

beforeEach(() => {
  mockSystemTheme(false);
});

function proofOf(fact: unknown) {
  return { fact, formula: null, parents: [], sources: [] };
}

function money(factId: number, display: string, value: string, name: string) {
  return { ...exact, fact_id: factId, display, value, name, change: true };
}

const OVERVIEW = {
  headline: "A critical problem needs your attention today.",
  narrative: null,
  sections: BRIEFING.sections,
  facts: BRIEFING.facts,
  names: NAMES,
};

const BRIDGE = {
  period_start: "2026-09-07",
  period_end: "2026-09-14",
  baseline_start: "2026-08-31",
  baseline_end: "2026-09-07",
  change: money(40, "+$724", "723.83", "Change in net profit"),
  drivers: [
    {
      driver: "volume",
      fact: money(41, "+$580", "579.60", "Effect of volume on net profit"),
      significant: true,
    },
    {
      driver: "mix",
      fact: money(42, "−$597", "-597.10", "Effect of product mix on net profit"),
      significant: false,
    },
    {
      driver: "unit_cost",
      fact: money(43, "$0", "0", "Effect of unit cost on net profit"),
      significant: null,
    },
  ],
};

describe("Home", () => {
  // A store with no morning brief yet: Home shows its day as assembled now.
  function today(extra: (fake: FakeApi) => FakeApi = (f) => f) {
    return extra(
      signedInApi()
        .on(`GET ${BASE}/briefings`, { items: [], next_cursor: null })
        .on(`GET ${BASE}/overview`, OVERVIEW)
        .on(`GET ${BASE}/profit-bridge`, BRIDGE),
    );
  }

  it("shows the store's day and what moved its net profit, every number a proof", async () => {
    renderApp("/today", today().api); // Today's old address lands on Home
    expect(await screen.findByRole("heading", { name: OVERVIEW.headline, level: 1 })).toBeVisible();
    const store = await screen.findByRole("region", { name: "Your store" });
    expect(within(store).getByRole("button", { name: "$1,235, see the proof" })).toBeVisible();
    const bridge = screen.getByRole("region", { name: "What moved your net profit" });
    expect(
      within(bridge).getByText("Sep 7 – Sep 13, 2026, against Aug 31 – Sep 6, 2026"),
    ).toBeVisible();
    expect(within(bridge).getByRole("button", { name: "+$724, see the proof" })).toBeVisible();
    expect(within(bridge).getByText("Effect of product mix on net profit")).toBeVisible();
    expect(within(bridge).getAllByText("Within its usual variation")).toHaveLength(1);
    expect(bridge.querySelectorAll('[data-part="gain"]')).toHaveLength(1);
    expect(bridge.querySelectorAll('[data-part="loss"]')).toHaveLength(1);
    expect(within(bridge).queryByText(/No driver stands out/)).toBeNull();
  });

  it("lists the goals in progress, the one being followed first", async () => {
    const goal = (id: string, status: string, restatement: string) => ({
      goal_id: id,
      status,
      restatement,
      facts: {},
      names: {},
    });
    const fake = today((f) =>
      f.on(`GET ${BASE}/goals`, [
        goal("g-long", "confirmed", "Your goal: six months."),
        goal("g-done", "achieved", "Your goal: last quarter."),
        goal("g-plan", "planned", "Your goal: three months."),
      ]),
    );
    renderApp("/", fake.api);
    const goals = await screen.findByRole("region", { name: "Your goals" });
    const rows = within(goals).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      "Your goal: three months.Following its plan",
      "Your goal: six months.Confirmed",
    ]);
    expect(within(goals).getByRole("link", { name: "All goals" })).toHaveAttribute(
      "href",
      "/goals",
    );
  });

  it("says when no driver stands out, and opens a problem in the conversation", async () => {
    const quiet = {
      ...BRIDGE,
      drivers: BRIDGE.drivers.map((d) => ({ ...d, significant: false })),
    };
    const fake = today((f) =>
      f
        .on(`GET ${BASE}/profit-bridge`, quiet)
        .on(`GET ${BASE}/briefings`, { items: [], next_cursor: null })
        .on(`GET ${BASE}/decisions/${DECISION}`, decision("proposed"))
        .on(`GET ${BASE}/facts/21`, proofOf(impact))
        .on(`GET ${BASE}/facts/22`, proofOf(zero))
        .on(`POST ${BASE}/policy/preview`, { allowed: true, rule: "ok", reason: "ok" }),
    );
    renderApp("/today", fake.api);
    expect(await screen.findByText(/No driver stands out/)).toBeVisible();
    await userEvent.click(await screen.findByRole("button", { name: "See options" }));
    // The decision opens on the Decisions page, its row expanded into the approval moment.
    expect(await screen.findByRole("heading", { name: "Decisions", level: 1 })).toBeVisible();
  });

  it("says when the day or the profit drivers cannot be read", async () => {
    const fake = today((f) =>
      f
        .on(`GET ${BASE}/overview`, () => problem(503, "down"))
        .on(`GET ${BASE}/profit-bridge`, () => problem(503, "down")),
    );
    renderApp("/today", fake.api);
    expect(await screen.findByText("Today’s overview could not be loaded.")).toBeVisible();
    expect(await screen.findByText("What moved your profit could not be loaded.")).toBeVisible();
  });
});

const MEASURED = "d-measured";
const HELD_ABOVE = "Better than predicted: the measured effect is above the predicted range.";
const OWNER = "d-owner";
const effect = estimateFact(
  30,
  ["23.00", "640.00", "1299.00"],
  ["$23.00", "$640.00", "$1,299.00"],
  ["+$23", "+$640", "+$1,299"],
  true,
);

function decisions() {
  return {
    items: [
      decision("proposed"),
      decision("executed", { decision_id: "d-done" }),
      decision("measured", {
        decision_id: MEASURED,
        outcomes: [
          {
            outcome_id: "o-1",
            action_id: "a-1",
            status: "measured",
            method: "synthetic_control_v2",
            window_start: "2026-09-15",
            window_end: "2026-09-22",
            effect_fact_id: 30,
            predicted_fact_id: 21,
            verdict: "above",
            verdict_text: HELD_ABOVE,
            reason: "measured",
          },
        ],
      }),
      decision("measured", {
        decision_id: OWNER,
        source: "owner",
        recommended_option_id: "owner",
        approved_option_id: "owner",
        label: "Raise the daily budget of ‘Trail Jacket — Prospecting’ by 20%?",
        options: [option("owner", "Raise the daily budget by 20%", null)],
        outcomes: [
          {
            outcome_id: "o-2",
            action_id: "a-2",
            status: "measured",
            method: "synthetic_control_v2",
            window_start: "2026-09-08",
            window_end: "2026-09-15",
            effect_fact_id: 30,
            predicted_fact_id: null,
            verdict: null,
            verdict_text: null,
            reason: "measured",
          },
        ],
      }),
      decision("superseded", { decision_id: "d-old", approved_option_id: null }),
      decision("approved", { decision_id: "d-going" }),
    ],
    next_cursor: null,
  };
}

const TRUST = [
  {
    action_type: "pause_campaign",
    level: 2,
    measured: 1,
    abstained: 0,
    rollbacks: 0,
    confirmations: 1,
    threshold: 10,
    progress: "1 of 10 confirmations before I can ask to do this alone",
  },
  {
    action_type: "change_budget",
    level: 3,
    measured: 10,
    abstained: 0,
    rollbacks: 0,
    confirmations: 10,
    threshold: 10,
    proposal: "propose autonomy level 4 for change_budget",
    proposed_level: 4,
    progress: "My predictions held 10 times: I can ask to manage this within its scope.",
  },
];

describe("the Decisions page", () => {
  function page() {
    return signedInApi()
      .on(`GET ${BASE}/decisions`, decisions())
      .on(`GET ${BASE}/trust`, TRUST)
      .on(`GET ${BASE}/goals`, [])
      .on(`GET ${BASE}/facts/21`, proofOf(impact))
      .on(`GET ${BASE}/facts/22`, proofOf(zero))
      .on(`GET ${BASE}/facts/30`, proofOf(effect))
      .on(`POST ${BASE}/policy/preview`, { allowed: true, rule: "ok", reason: "ok" });
  }
  const measured = () => decisions().items.find((d) => d.decision_id === MEASURED);

  it("files the decisions in folders, the owner's first, each row with its amount", async () => {
    renderApp("/decisions", page().api);
    const list = await screen.findByRole("navigation", { name: "Decisions list" });
    const show = within(list).getByRole("group", { name: "Show" });
    expect(within(show).getByRole("button", { name: "To decide" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const waiting = within(list).getByRole("list", { name: "To decide" });
    const row = within(waiting).getByRole("link", { name: /until restock\?/ });
    expect(row).toHaveTextContent("Waiting for you");
    expect(row).toHaveTextContent("From an alert");
    expect(await within(row).findByText("+$613 to +$654")).toBeVisible();
    expect(screen.getByText("Pick a decision.")).toBeVisible();
    await userEvent.click(within(show).getByRole("button", { name: "Done" }));
    const done = within(list).getByRole("list", { name: "Done" });
    expect(within(done).getAllByRole("link")).toHaveLength(3);
    expect(await within(done).findAllByText("+$23 to +$1,299")).toHaveLength(2);
    await userEvent.click(within(show).getByRole("button", { name: "Closed" }));
    expect(within(list).getByRole("list", { name: "Closed" })).toHaveTextContent("Replaced");
  });

  it("opens a decision at its own address: why, then the approval card", async () => {
    const fake = page().on(`GET ${BASE}/decisions/${DECISION}`, decision("proposed"));
    const { router } = renderApp("/decisions", fake.api);
    const list = await screen.findByRole("navigation", { name: "Decisions list" });
    await userEvent.click(within(list).getByRole("link", { name: /until restock\?/ }));
    expect(router.state.location.pathname).toBe(`/decisions/${DECISION}`);
    const detail = await screen.findByRole("region", { name: decision("proposed").label });
    expect(within(detail).getByRole("heading", { level: 2 })).toHaveTextContent("until restock?");
    expect(within(detail).getAllByRole("heading", { level: 3 }).length).toBeGreaterThan(1);
    const why = within(detail).getByRole("region", { name: "Why" });
    expect(why).toHaveTextContent("Ads keep spending on a product that is out of stock.");
    expect(within(why).getByRole("button", { name: "What I checked" })).toBeVisible();
    const propose = within(detail).getByRole("region", { name: "What I propose" });
    expect(await within(propose).findByRole("button", { name: "Approve" })).toBeVisible();
  });

  it("asks about a decision in the conversation, with its questions", async () => {
    const fake = page().on(`GET ${BASE}/decisions/${DECISION}`, decision("proposed"));
    const { router } = renderApp(`/decisions/${DECISION}`, fake.api);
    await userEvent.click(await screen.findByRole("button", { name: "Ask about this decision" }));
    expect(router.state.location.pathname).toBe("/chat");
    expect(screen.getByText(decision("proposed").label)).toBeVisible();
    expect(screen.getByRole("button", { name: "What could go wrong?" })).toBeVisible();
  });

  it("reads a measured decision top to bottom: proposed, decided, happened, earned", async () => {
    const fake = page()
      .on(`GET ${BASE}/decisions/${MEASURED}`, measured())
      .on(`GET ${BASE}/journal`, {
        items: [
          {
            id: "ap-1",
            kind: "approval",
            at: "2026-09-15T08:12:00Z",
            summary: {
              decision_id: MEASURED,
              verdict: "approved",
              channel: "web",
              actor: "owner:o@x.io",
            },
            entities: [],
          },
        ],
        next_cursor: null,
        names: {},
        facts: {},
      });
    renderApp(`/decisions/${MEASURED}`, fake.api);
    const detail = await screen.findByRole("region", { name: /until restock$/ });
    const proposed = within(detail).getByRole("region", { name: "What I proposed" });
    expect(within(proposed).getByText("Chosen")).toBeVisible();
    expect(within(proposed).getByText("Do nothing")).toBeVisible();
    const decided = await within(detail).findByRole("region", { name: "What was decided" });
    expect(decided).toHaveTextContent("You approved it in the app.");
    const happened = within(detail).getByRole("region", { name: "What happened" });
    expect(await within(happened).findByText("Done and measured")).toBeVisible();
    const earned = within(detail).getByRole("region", { name: "What it earned" });
    expect(await within(earned).findByText("Predicted")).toBeVisible();
    expect(within(earned).getByText("Measured")).toBeVisible();
    expect(within(earned).getByText(HELD_ABOVE)).toBeVisible(); // the backend's verdict
    // Two periods, named: the option's forecast over its horizon, the measured week.
    expect(within(earned).getByText(/same week/)).toBeVisible();
    expect(within(detail).getByRole("region", { name: "Why" })).toHaveTextContent(
      "Expected over 14 days",
    );
    expect(
      await within(earned).findByText("1 of 10 confirmations before I can ask to do this alone"),
    ).toBeVisible();
  });

  it("names the goal step a decision carries out, linked to the goal", async () => {
    const step = {
      goal_id: "g-1",
      plan_id: "p-1",
      step_id: "s-1",
      position: 1,
      status: "proposed",
    };
    const fake = page()
      .on(`GET ${BASE}/decisions/${DECISION}`, decision("proposed", { goal_step: step }))
      .on(`GET ${BASE}/goals/g-1/plans`, [
        {
          plan_id: "p-1",
          goal_id: "g-1",
          status: "accepted",
          as_of: "2026-09-01",
          detailed_days: 90,
          payload: {},
          steps: [
            {
              step_id: "s-1",
              position: 1,
              lever: "scale_profitable",
              kind: "decision",
              due_date: "2026-09-01",
              actions: [],
              summary: "Raise the daily budget of {{E:store}}.",
              evidence: [],
              effect_fact_id: null,
              status: "proposed",
              decision_id: DECISION,
            },
          ],
          facts: {},
          names: { store: "Northwind Outdoor" },
        },
      ]);
    renderApp(`/decisions/${DECISION}`, fake.api);
    const linked = await screen.findByRole("region", { name: "Linked to" });
    expect(linked).toHaveTextContent("Step 1 of your goal's plan");
    const link = await within(linked).findByRole("link", {
      name: "Raise the daily budget of Northwind Outdoor.",
    });
    expect(link).toHaveAttribute("href", "/goals/g-1");
  });

  it("moves through the list with the arrow keys, as a mail client does", async () => {
    const fake = page()
      .on(`GET ${BASE}/decisions/d-done`, decisions().items[1])
      .on(`GET ${BASE}/decisions/${MEASURED}`, measured());
    const { router } = renderApp("/decisions/d-done", fake.api);
    const list = await screen.findByRole("list", { name: "Done" });
    const rows = within(list).getAllByRole("link");
    expect(rows[0]).toHaveAttribute("aria-current", "page");
    rows[0]?.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(router.state.location.pathname).toBe(`/decisions/${MEASURED}`);
    expect(rows[1]).toHaveFocus();
  });

  it("moves an approved decision to In progress, still open", async () => {
    let status = "proposed";
    const listed = () => {
      const all = decisions();
      return { ...all, items: all.items.map((d, i) => (i === 0 ? decision(status) : d)) };
    };
    const fake = page()
      .on(`GET ${BASE}/decisions`, () => json(listed()))
      .on(`GET ${BASE}/decisions/${DECISION}`, () => json(decision(status)))
      .on(`POST ${BASE}/decisions/${DECISION}/approve`, () => {
        status = "approved";
        return json(decision("approved"));
      });
    renderApp(`/decisions/${DECISION}`, fake.api);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    // The list is read again: the decision moves to "In progress"; it stays open on the right.
    const show = await screen.findByRole("group", { name: "Show" });
    await waitFor(() => {
      expect(within(show).getByRole("button", { name: "In progress" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    const detail = screen.getByRole("region", { name: /until restock$/ });
    expect(await within(detail).findByRole("status")).toHaveTextContent("Approved: starting");
  });

  it("still opens a decision from an old link", async () => {
    const fake = page().on(`GET ${BASE}/decisions/${DECISION}`, decision("proposed"));
    const { router } = renderApp(`/decisions?open=${DECISION}`, fake.api);
    await screen.findByRole("region", { name: decision("proposed").label });
    expect(router.state.location.pathname).toBe(`/decisions/${DECISION}`);
  });

  it("says when there is none, or they cannot be read", async () => {
    const none = signedInApi()
      .on(`GET ${BASE}/decisions`, { items: [], next_cursor: null })
      .on(`GET ${BASE}/trust`, []);
    const { unmount } = renderApp("/decisions", none.api);
    expect(await screen.findByText("No decision yet.")).toBeVisible();
    unmount();
    renderApp("/decisions", none.on(`GET ${BASE}/decisions`, () => problem(503, "down")).api);
    expect(await screen.findByText("The decisions could not be loaded.")).toBeVisible();
  });
});

describe("the Journal", () => {
  const at = (day: string, time: string) => `2026-${day}T${time}:00Z`;
  const BEFORE = { ...exact, fact_id: 41, display: "$68.57", name: "Daily budget before" };
  const AFTER = { ...exact, fact_id: 42, display: "$82.28", name: "Daily budget after" };
  const ENTRIES = [
    {
      id: "a-1",
      kind: "action",
      at: at("11-02", "19:37"),
      summary: {
        decision_id: DECISION,
        kind: "pause_campaign",
        campaign_id: CAMPAIGN,
        provider: "simulator",
        status: "executed",
        after: { status: "PAUSED" },
      },
      entities: [`campaign:${CAMPAIGN}`],
    },
    {
      id: "ap-1",
      kind: "approval",
      at: at("11-02", "19:36"),
      summary: { decision_id: DECISION, verdict: "approved", option_id: "pause", channel: "email" },
    },
    { id: DECISION, kind: "decision", at: at("11-02", "19:35"), summary: { status: "executed" } },
    {
      id: INCIDENT,
      kind: "incident",
      at: at("11-02", "19:34"),
      summary: { alert: "critical", category: "profitability" },
      entities: [`product:${PRODUCT}`, `campaign:${CAMPAIGN}`],
    },
    {
      id: "o-1",
      kind: "outcome",
      at: at("10-26", "10:00"),
      summary: {
        decision_id: OWNER,
        status: "measured",
        effect_fact_id: 30,
        verdict: "above",
        verdict_text: HELD_ABOVE,
      },
    },
    {
      id: "o-2",
      kind: "outcome",
      at: at("10-26", "09:00"),
      summary: { decision_id: OWNER, status: "abstained", effect_fact_id: null },
    },
    {
      id: "a-2",
      kind: "action",
      at: at("10-25", "09:00"),
      summary: { decision_id: OWNER, status: "failed", error: "the token expired" },
    },
    {
      id: "a-3",
      kind: "action",
      at: at("10-25", "08:00"),
      summary: { decision_id: OWNER, status: "executed", rollback_of: "a-0", provider: "meta" },
    },
    {
      id: "a-4",
      kind: "action",
      at: at("10-25", "07:00"),
      summary: {
        decision_id: OWNER,
        kind: "change_budget",
        status: "executed",
        budget_before_fact_id: 41,
        budget_after_fact_id: 42,
      },
    },
    {
      id: "ap-2",
      kind: "approval",
      at: at("10-24", "08:00"),
      summary: { decision_id: "d-old", verdict: "rejected", channel: "whatsapp" },
    },
    { id: OWNER, kind: "decision", at: at("10-24", "07:00"), summary: {} },
    { id: "x", kind: "mystery", at: at("10-24", "06:00"), summary: {} },
  ];

  function journal(pages = [ENTRIES]) {
    let call = 0;
    return signedInApi()
      .on(`GET ${BASE}/journal`, () => {
        const items = pages[call] ?? [];
        call += 1;
        return json({
          items: items.map((e) => ({ entities: [], ...e })),
          next_cursor: call < pages.length ? `c${String(call)}` : null,
          names: NAMES,
          facts: { "30": effect, "41": BEFORE, "42": AFTER },
        });
      })
      .on(`GET ${BASE}/decisions`, decisions())
      .on(`GET ${BASE}/facts/30`, proofOf(effect));
  }

  it("tells what happened, newest first, day by day", async () => {
    renderApp("/journal", journal([ENTRIES.slice(0, 5), ENTRIES.slice(5)]).api);
    const latest = await screen.findByRole("region", { name: "Mon, Nov 2" });
    const lines = within(latest).getAllByRole("listitem");
    expect(lines[0]).toHaveTextContent(
      "Carried out: Pause ‘Trail Jacket — Prospecting’ until restock",
    );
    expect(lines[0]).toHaveTextContent("The ad platform reports the campaign paused.");
    expect(lines[0]).toHaveTextContent("7:37 PM");
    expect(lines[1]).toHaveTextContent(
      "You approved by email: Pause ‘Trail Jacket — Prospecting’ until restock",
    );
    expect(lines[2]).toHaveTextContent("I proposed: Pause ‘Trail Jacket — Prospecting’ until");
    expect(lines[2]).toHaveTextContent("Waiting for you"); // its status now
    expect(lines[3]).toHaveTextContent("A critical problem was found in profitability");
    expect(lines[3]).toHaveTextContent("About Trail Jacket, Trail Jacket — Prospecting.");
    const measured = screen.getByRole("region", { name: "Mon, Oct 26" });
    expect(
      await within(measured).findByRole("button", { name: "+$23 to +$1,299, see the proof" }),
    ).toBeVisible();
    expect(measured).toHaveTextContent("Could not be measured: Raise the daily budget by 20%");
    expect(measured).toHaveTextContent(HELD_ABOVE);
    const older = screen.getByRole("region", { name: "Sun, Oct 25" });
    expect(older).toHaveTextContent("Could not be carried out: Raise the daily budget by 20%");
    expect(older).toHaveTextContent("the token expired");
    expect(older).toHaveTextContent("Undone: Raise the daily budget by 20%");
    expect(within(older).getByRole("button", { name: "$68.57, see the proof" })).toBeVisible();
    expect(older).toHaveTextContent(/Daily budget: \$68\.57.* before, \$82\.28.* after/);
    const first = screen.getByRole("region", { name: "Sat, Oct 24" });
    expect(first).toHaveTextContent("You said not now on WhatsApp:");
    expect(first).toHaveTextContent("You asked: Raise the daily budget by 20%");
    expect(first).toHaveTextContent("mystery");
  });

  it("opens what was checked about a problem in the conversation", async () => {
    const fake = journal()
      .on(`GET ${BASE}/briefings`, { items: [], next_cursor: null })
      .on(`GET ${BASE}/incidents/${INCIDENT}`, () => problem(404, "not_found"));
    renderApp("/journal", fake.api);
    await userEvent.click(await screen.findByRole("button", { name: "What I checked" }));
    expect(await screen.findByText("This problem could not be loaded.")).toBeInTheDocument();
  });

  it("says when nothing happened yet, or it cannot be read", async () => {
    const { unmount } = renderApp("/journal", journal([[]]).api);
    expect(await screen.findByText("Nothing has happened yet.")).toBeVisible();
    unmount();
    renderApp("/journal", journal().on(`GET ${BASE}/journal`, () => problem(503, "down")).api);
    expect(await screen.findByText("The journal could not be loaded.")).toBeVisible();
  });
});

describe("Settings", () => {
  const SETTINGS = {
    store_id: STORE_ID,
    currency: "USD",
    timezone: "UTC",
    language: "en",
    alert_channels: ["web", "email"],
    autonomy: { pause_campaign: 2, change_budget: 3, resume_campaign: 1 },
  };

  it("says, per kind of action, its rule and how far it was earned, then the channels", async () => {
    const fake = signedInApi().on(`GET ${BASE}/settings`, SETTINGS).on(`GET ${BASE}/trust`, TRUST);
    renderApp("/settings", fake.api);
    const may = await screen.findByRole("region", { name: "What I may do" });
    const pause = within(may).getByRole("listitem", { name: "Pausing a campaign" });
    expect(within(pause).getByText("Needs your approval")).toBeVisible();
    expect(
      within(pause).getByText("1 of 10 confirmations before I can ask to do this alone"),
    ).toBeVisible();
    const budget = within(may).getByRole("listitem", { name: "Changing a daily budget" });
    expect(within(budget).getByText("Allowed")).toBeVisible();
    const resume = within(may).getByRole("listitem", { name: "Resuming a campaign" });
    expect(within(resume).getByText("Blocked")).toBeVisible();
    const channels = screen.getByRole("region", { name: "Where I reach you" });
    expect(within(channels).getAllByText("On")).toHaveLength(2);
    expect(within(channels).getAllByText("Off")).toHaveLength(1);
  });

  it("says when the settings cannot be read", async () => {
    const fake = signedInApi()
      .on(`GET ${BASE}/settings`, () => problem(503, "down"))
      .on(`GET ${BASE}/trust`, []);
    renderApp("/settings", fake.api);
    expect(await screen.findByText("Your settings could not be loaded.")).toBeVisible();
  });
});
