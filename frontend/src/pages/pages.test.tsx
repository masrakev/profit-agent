import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  BRIEFING,
  CAMPAIGN,
  DECISION,
  INCIDENT,
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

describe("Today", () => {
  function today(extra: (fake: FakeApi) => FakeApi = (f) => f) {
    return extra(
      signedInApi().on(`GET ${BASE}/overview`, OVERVIEW).on(`GET ${BASE}/profit-bridge`, BRIDGE),
    );
  }

  it("shows the store's day and what moved its net profit, every number a proof", async () => {
    renderApp("/today", today().api);
    expect(await screen.findByRole("heading", { name: "Today", level: 1 })).toBeVisible();
    expect(await screen.findByText(OVERVIEW.headline)).toBeVisible();
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
    await userEvent.click(screen.getByRole("button", { name: "See options" }));
    expect(
      await screen.findByRole("article", { name: decision("proposed").label }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Chat" })).toBeInTheDocument();
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
      decision("measured", { decision_id: MEASURED }),
      decision("measured", {
        decision_id: OWNER,
        source: "owner",
        recommended_option_id: "owner",
        approved_option_id: "owner",
        label: "Raise the daily budget of ‘Trail Jacket — Prospecting’ by 20%?",
        options: [option("owner", "Raise the daily budget by 20%", null)],
      }),
      decision("superseded", { decision_id: "d-old", approved_option_id: null }),
      decision("approved", { decision_id: "d-going" }),
    ],
    next_cursor: null,
  };
}

function outcome(decisionId: string, factId: number) {
  return {
    id: `o-${decisionId}`,
    kind: "outcome",
    at: "2026-10-26T10:00:00Z",
    summary: { decision_id: decisionId, status: "measured", effect_fact_id: factId },
  };
}

const TRUST = [
  { action_type: "pause_campaign", level: 2, measured: 0, abstained: 0, rollbacks: 0 },
  {
    action_type: "change_budget",
    level: 3,
    measured: 10,
    abstained: 0,
    rollbacks: 0,
    proposal: "propose autonomy level 4 for change_budget",
  },
];

describe("the Decisions page", () => {
  function page() {
    return signedInApi()
      .on(`GET ${BASE}/decisions`, decisions())
      .on(`GET ${BASE}/journal`, {
        items: [outcome(MEASURED, 30), outcome(OWNER, 30)],
        next_cursor: null,
      })
      .on(`GET ${BASE}/trust`, TRUST)
      .on(`GET ${BASE}/facts/21`, proofOf(impact))
      .on(`GET ${BASE}/facts/30`, proofOf(effect));
  }

  it("lists the decisions by where they stand, with what each expected and measured", async () => {
    renderApp("/decisions", page().api);
    const waiting = await screen.findByRole("region", { name: "Waiting for you" });
    const proposed = within(waiting).getByRole("article", { name: decision("proposed").label });
    expect(within(proposed).getByText("Waiting for you")).toBeVisible();
    expect(within(proposed).getByText(/From an alert ·/)).toBeVisible();
    expect(
      await within(proposed).findByText("Expected, compared with doing nothing:"),
    ).toBeVisible();
    const done = screen.getByRole("region", { name: "Done" });
    const both = within(done).getAllByRole("article")[1];
    expect(both).toBeDefined();
    const measured = within(both!);
    expect(await measured.findByText("Predicted")).toBeVisible();
    expect(measured.getByText("Measured")).toBeVisible();
    expect(measured.getByRole("button", { name: "+$23 to +$1,299, see the proof" })).toBeVisible();
    const asked = within(done).getByRole("article", { name: "Raise the daily budget by 20%" });
    expect(within(asked).getByText(/You asked ·/)).toBeVisible();
    expect(within(asked).queryByText("Predicted")).toBeNull(); // nothing was predicted as a fact
    expect(await within(asked).findByText("Measured")).toBeVisible();
    expect(screen.getByRole("region", { name: "In progress" })).toHaveTextContent(
      "Approved: starting",
    );
    expect(screen.getByRole("region", { name: "Closed" })).toHaveTextContent(
      "Replaced by a newer decision.",
    );
  });

  it("shows how far it may act alone, and offers more only when it is proposed", async () => {
    renderApp("/decisions", page().api);
    const autonomy = await screen.findByRole("region", { name: "Earned autonomy" });
    expect(within(autonomy).getByText("Pausing a campaign")).toBeVisible();
    expect(within(autonomy).getByText("I ask you first, every time")).toBeVisible();
    expect(within(autonomy).getByText("I act alone within your caps")).toBeVisible();
    const allow = within(autonomy).getAllByRole("link", { name: "Always allow" });
    expect(allow).toHaveLength(1);
    expect(allow[0]).toHaveAttribute("href", "/settings");
  });

  it("opens a decision in the conversation", async () => {
    const fake = page()
      .on(`GET ${BASE}/briefings`, { items: [], next_cursor: null })
      .on(`GET ${BASE}/decisions/${DECISION}`, decision("proposed"))
      .on(`GET ${BASE}/facts/22`, proofOf(zero))
      .on(`POST ${BASE}/policy/preview`, { allowed: true, rule: "ok", reason: "ok" });
    renderApp("/decisions", fake.api);
    const waiting = await screen.findByRole("region", { name: "Waiting for you" });
    await userEvent.click(within(waiting).getByRole("button", { name: "Review" }));
    expect(await screen.findByRole("heading", { name: "Chat" })).toBeInTheDocument();
  });

  it("says when there is none, or they cannot be read", async () => {
    const none = signedInApi()
      .on(`GET ${BASE}/decisions`, { items: [], next_cursor: null })
      .on(`GET ${BASE}/journal`, { items: [], next_cursor: null })
      .on(`GET ${BASE}/trust`, []);
    const { unmount } = renderApp("/decisions", none.api);
    expect(await screen.findByText("No decision yet.")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Earned autonomy" })).toBeNull();
    unmount();
    renderApp("/decisions", none.on(`GET ${BASE}/decisions`, () => problem(503, "down")).api);
    expect(await screen.findByText("The decisions could not be loaded.")).toBeVisible();
  });
});

describe("the Journal", () => {
  const at = (day: string, time: string) => `2026-${day}T${time}:00Z`;
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
    },
    {
      id: "o-1",
      kind: "outcome",
      at: at("10-26", "10:00"),
      summary: { decision_id: OWNER, status: "measured", effect_fact_id: 30 },
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
        return json({ items, next_cursor: call < pages.length ? `c${String(call)}` : null });
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
    const measured = screen.getByRole("region", { name: "Mon, Oct 26" });
    expect(
      await within(measured).findByRole("button", { name: "+$23 to +$1,299, see the proof" }),
    ).toBeVisible();
    expect(measured).toHaveTextContent("Could not be measured: Raise the daily budget by 20%");
    const older = screen.getByRole("region", { name: "Sun, Oct 25" });
    expect(older).toHaveTextContent("Could not be carried out: Raise the daily budget by 20%");
    expect(older).toHaveTextContent("the token expired");
    expect(older).toHaveTextContent("Undone: Raise the daily budget by 20%");
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
