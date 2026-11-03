import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Blob as NodeBlob } from "node:buffer";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reduce, extension } from "./model";
import { RichText } from "./RichText";
import { stepText, visibleSteps } from "./steps";
import {
  ANSWER,
  BRIEFING,
  CAMPAIGN,
  DECISION,
  INCIDENT,
  INVESTIGATION,
  NAMES,
  PRODUCT,
  decision,
  impact,
  zero,
} from "@/test/conversation";
import { exact } from "@/test/facts";
import { fakeApi, json, problem, sse } from "@/test/fakeApi";
import { mockSystemTheme } from "@/test/matchMedia";
import { renderApp, renderInStore, signedInApi, STORE_ID } from "@/test/render";

const BASE = `/api/v1/stores/${STORE_ID}`;

beforeEach(() => {
  mockSystemTheme(false);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function store() {
  return signedInApi()
    .on(`GET ${BASE}/briefings`, {
      items: [{ ...BRIEFING, kind: "weekly", briefing_id: "w" }, BRIEFING],
      next_cursor: null,
    })
    .on(`GET ${BASE}/briefings/${BRIEFING.briefing_id}`, BRIEFING);
}

describe("text with references", () => {
  it("shows facts as numbers that open their proof, and entities by name", async () => {
    const fake = fakeApi().on(`GET ${BASE}/facts/7`, {
      fact: { ...exact, fact_id: 7, display: "$70" },
      formula: null,
      parents: [],
      sources: [],
    });
    renderInStore(
      <p>
        <RichText
          text={`{{E:store}} sold {{F12}} of {{E:product:${PRODUCT}}}, then {{F7}} via {{E:campaign:${CAMPAIGN}}}; {{E:product:00000000-0000-0000-0000-000000000000}} too.`}
          facts={{ "12": exact }}
          names={NAMES}
        />
      </p>,
      fake.api,
    );
    expect(screen.getByRole("paragraph")).toHaveTextContent(
      "Northwind Outdoor sold $1,235, see the proof of Trail Jacket, then … via Trail Jacket — Prospecting; a product too.",
    );
    expect(await screen.findByRole("button", { name: "$70, see the proof" })).toBeInTheDocument();
  });

  it("says when a cited number cannot be read", async () => {
    renderInStore(<RichText text="{{F8}}" facts={{}} names={{}} />, fakeApi().api);
    expect(await screen.findByText("(unavailable)")).toBeInTheDocument();
  });
});

describe("the agent's steps", () => {
  it("are told in words, naming what they looked at", () => {
    const tool = (name: string, args: unknown) => ({
      kind: "tool",
      name,
      detail: { ok: true, arguments: JSON.stringify(args) },
    });
    expect(stepText(tool("get_inventory_context", { product_id: PRODUCT }), NAMES)).toBe(
      "Checked the stock of Trail Jacket",
    );
    expect(stepText(tool("get_campaign_context", { campaign_id: CAMPAIGN }), NAMES)).toBe(
      "Looked at ‘Trail Jacket — Prospecting’",
    );
    expect(stepText(tool("get_campaign_context", { campaign_id: "x" }), {})).toBe(
      "Looked at a campaign",
    );
    expect(
      stepText(tool("get_facts", { metric: "ad_spend", scope: { kind: "product", id: "y" } }), {}),
    ).toBe("Read ad spend for a product");
    expect(stepText(tool("get_facts", { scope: { kind: "store" } }), {})).toBe(
      "Read a figure for the store",
    );
    expect(stepText(tool("get_data_quality", {}), {})).toBe(
      "Checked the data is complete and up to date",
    );
    expect(stepText({ kind: "tool", name: "brand_new", detail: { arguments: "{oops" } }, {})).toBe(
      "Brand new",
    );
    expect(stepText({ kind: "model", name: "m", detail: {} }, {})).toBe("Weighed the evidence");
    expect(stepText({ kind: "mystery", name: null, detail: {} }, {})).toBe("Mystery");
    expect(
      visibleSteps([
        { kind: "started", name: null, detail: {} },
        { kind: "tool", name: "x", detail: {} },
        { kind: "done", name: null, detail: {} },
      ]),
    ).toHaveLength(1);
  });

  it("name the recording's container for the server", () => {
    expect(extension("audio/webm;codecs=opus")).toBe("webm");
    expect(extension("audio/mp4")).toBe("m4a");
    expect(extension("audio/ogg")).toBe("ogg");
    expect(extension("audio/wav")).toBe("wav");
    expect(reduce([], { type: "failed", id: 1, problem: "x" })).toEqual([]);
  });
});

describe("the morning brief", () => {
  it("opens the conversation: the day, the picture, what needs the owner", async () => {
    renderApp("/", store().api);
    const brief = await screen.findByRole("article", { name: "Morning brief" });
    expect(within(brief).getByText("Tue, Sep 15")).toBeInTheDocument();
    expect(within(brief).getByText("7:30 AM")).toBeInTheDocument(); // sent, not generated
    expect(within(brief).getByRole("heading", { name: BRIEFING.headline })).toBeInTheDocument();
    expect(within(brief).getAllByText("Trail Jacket").length).toBeGreaterThan(0);
    const picture = within(brief).getByRole("region", { name: "Your weekly picture" });
    expect(within(picture).getByRole("button", { name: "$1,235, see the proof" })).toBeVisible();
    expect(within(picture).getByText("Most likely")).toBeInTheDocument();
    expect(within(picture).getByText("Data stops before yesterday.")).toBeInTheDocument();
    expect(within(brief).getByRole("region", { name: "Worth your attention" })).toHaveTextContent(
      "critical",
    );
    expect(within(brief).getByRole("region", { name: "Pending decisions" })).toHaveTextContent(
      "Trail Jacket — Prospecting: raise the daily budget",
    );
    expect(within(brief).getByText("Nothing to watch.")).toBeInTheDocument();
  });

  it("says when there is none yet, or when it cannot be read", async () => {
    renderApp("/", signedInApi().on(`GET ${BASE}/briefings`, { items: [], next_cursor: null }).api);
    expect(await screen.findByText(/No morning brief yet/)).toBeInTheDocument();
  });

  it("says when it cannot be read", async () => {
    renderApp("/", signedInApi().on(`GET ${BASE}/briefings`, () => problem(503, "down")).api);
    expect(await screen.findByText("The morning brief could not be loaded.")).toBeInTheDocument();
  });
});

describe("asking", () => {
  it("streams the agent's work, then the answer with its proofs", async () => {
    const fake = store().on(`POST ${BASE}/ask/stream`, () =>
      sse(
        ["step", { kind: "started", name: null, detail: {} }],
        [
          "step",
          {
            kind: "tool",
            name: "get_inventory_context",
            detail: { ok: true, arguments: JSON.stringify({ product_id: PRODUCT }) },
          },
        ],
        [
          "step",
          { kind: "tool", name: "get_data_quality", detail: { ok: false, arguments: "{}" } },
        ],
        ["answer", ANSWER],
        ["done", {}],
      ),
    );
    renderApp("/", fake.api);
    const box = await screen.findByRole("textbox", { name: "Ask anything about your store" });
    await userEvent.type(box, "What should I do about the jacket?{Enter}");
    expect(screen.getByText("What should I do about the jacket?")).toBeInTheDocument();
    const answer = await screen.findByRole("article", { name: "Answer" });
    expect(answer).toHaveTextContent(/it spent/);
    const sent = fake.requests.find((r) => r.url.endsWith("/ask/stream"));
    expect(await sent?.json()).toEqual({ question: "What should I do about the jacket?" });
    expect(within(answer).getAllByRole("button", { name: "$1,235, see the proof" })).toHaveLength(
      2,
    );
    const evidence = within(answer).getByRole("region", { name: "Evidence" });
    expect(within(evidence).getByText("Net profit")).toBeVisible(); // each fact named, with its value
    expect(within(answer).getByText("Trail Jacket — Prospecting")).toBeInTheDocument();
    expect(within(answer).getByText(/Next step:/).parentElement).toHaveTextContent(
      "Pause until restock, expected +$613 to +$654",
    );
    expect(within(answer).getByText(/Still uncertain:/)).toBeVisible();
    expect(within(answer).getByText(/not checked against orders/)).toBeInTheDocument();
    const reply = within(answer.parentElement!);
    await userEvent.click(reply.getByRole("button", { name: "What I checked" }));
    expect(reply.getByText("Checked the stock of Trail Jacket")).toBeVisible();
    expect(reply.getByText("(it failed)")).toBeInTheDocument();
    await userEvent.click(within(answer).getByRole("button", { name: "How I got there" }));
    expect(within(answer).getByText("Cut the budget instead.")).toBeVisible();
    expect(within(answer).getByText(/A restock this week/)).toBeVisible();
    await userEvent.click(within(answer).getByRole("button", { name: "Verified" }));
    expect(within(answer).getByRole("button", { name: "See the proof" })).toBeInTheDocument();
  });

  it("says when the answer could not be completed", async () => {
    const fake = store().on(`POST ${BASE}/ask/stream`, () =>
      sse(["step", { kind: "started", name: null, detail: {} }], ["failed", { error: "X" }]),
    );
    renderApp("/", fake.api);
    await userEvent.type(await screen.findByRole("textbox"), "Hello{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be completed");
  });

  it("says when the stream ends without an answer, or is refused", async () => {
    let calls = 0;
    const fake = store().on(`POST ${BASE}/ask/stream`, () => {
      calls += 1;
      return calls === 1
        ? sse(["step", { kind: "started", name: null, detail: {} }])
        : problem(429, "rate_limited");
    });
    renderApp("/", fake.api);
    const box = await screen.findByRole("textbox");
    await userEvent.type(box, "One{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be completed");
    await userEvent.type(box, "Two{Enter}");
    await waitFor(() => {
      expect(screen.getAllByRole("alert")[1]).toHaveTextContent("Too many questions");
    });
  });
});

describe("asking by voice", () => {
  // jsdom's Blob cannot travel in a fetch body: these tests send Node's own, as a browser would.
  beforeEach(async () => {
    const form = await new Response("a=b", {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    }).formData();
    vi.stubGlobal("FormData", form.constructor);
  });

  function recorder() {
    return () => ({
      start: () => Promise.resolve(),
      stop: () => Promise.resolve(new NodeBlob(["sound"], { type: "audio/webm" }) as Blob),
      cancel: vi.fn(),
      samples: () => new Uint8Array([128, 200, 60]),
    });
  }

  it("shows what was heard, then the answer", async () => {
    const fake = store().on(`POST ${BASE}/ask/voice`, () =>
      sse(
        ["transcript", { transcript: "What should I do?", heard: true }],
        ["answer", ANSWER],
        ["done", {}],
      ),
    );
    const { Composer } = await import("@/shell/Composer");
    const { ConversationProvider } = await import("./ConversationProvider");
    const { useConversation } = await import("./context");
    const { ChatPage } = await import("@/pages/ChatPage");
    function Dock() {
      const { askByVoice } = useConversation();
      return <Composer onVoice={askByVoice} recorder={recorder()} />;
    }
    renderInStore(
      <ConversationProvider>
        <ChatPage />
        <Dock />
      </ConversationProvider>,
      fake.api,
    );
    await userEvent.click(screen.getByRole("button", { name: "Ask by voice" }));
    expect(screen.getByRole("group", { name: "Recording your question" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("What should I do?")).toBeInTheDocument();
    expect(await screen.findByText(/it spent/)).toBeInTheDocument();
    const sent = fake.requests.find((r) => r.url.endsWith("/ask/voice"));
    expect(sent?.headers.get("content-type")).toMatch(/^multipart\/form-data/);
  });

  it("says when nothing was heard, or the recording was refused", async () => {
    let calls = 0;
    const fake = store().on(`POST ${BASE}/ask/voice`, () => {
      calls += 1;
      if (calls === 1)
        return sse(["transcript", { heard: false }], ["no_speech", {}], ["done", {}]);
      return problem(422, "audio_too_long");
    });
    const { ConversationProvider } = await import("./ConversationProvider");
    const { useConversation } = await import("./context");
    const { ChatPage } = await import("@/pages/ChatPage");
    function Ask() {
      const { askByVoice } = useConversation();
      return (
        <button
          type="button"
          onClick={() => {
            askByVoice(new NodeBlob(["x"], { type: "audio/mp4" }) as Blob);
          }}
        >
          speak
        </button>
      );
    }
    renderInStore(
      <ConversationProvider>
        <ChatPage />
        <Ask />
      </ConversationProvider>,
      fake.api,
    );
    await userEvent.click(screen.getByRole("button", { name: "speak" }));
    expect(await screen.findByText(/No speech was heard/)).toBeInTheDocument();
    expect(screen.getByText("Your recorded question")).toBeInTheDocument();
    expect(screen.queryByText("Listening to your question…")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "speak" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("over two minutes");
  });
});

describe("what was checked about a problem", () => {
  const steps = [
    { seq: 1, kind: "started", name: null, detail: {}, created_at: "2026-11-02T10:00:00Z" },
    {
      seq: 2,
      kind: "tool",
      name: "get_inventory_context",
      detail: { ok: true, arguments: JSON.stringify({ product_id: PRODUCT }) },
      created_at: "2026-11-02T10:00:01Z",
    },
  ];
  const report = {
    investigation_id: INVESTIGATION,
    status: "complete",
    report: {
      hypotheses: [
        {
          cause_family: "stockout_on_promoted",
          entities: [`{{E:product:${PRODUCT}}}`, `{{E:campaign:${CAMPAIGN}}}`],
          confidence: "high",
          evidence: [12],
          tests_performed: ["checked stock against lead time"],
          counter_evidence: [],
        },
      ],
      narrative: "Spend kept going as in {{F12}}, then {{F14}}.",
      flags: [],
      open_questions: [],
      audit_findings: [],
    },
    duration: "41 s",
    facts: { "14": { ...exact, fact_id: 14, display: "$140" } }, // cited by the report only
    names: {},
  };
  function incident(extra: Record<string, unknown> = {}) {
    return {
      incident: { incident_id: INCIDENT },
      facts: { "12": exact },
      names: NAMES,
      investigation_ids: [INVESTIGATION],
      decision_ids: [DECISION],
      ...extra,
    };
  }

  it("shows the steps, the likely cause with its checks, and the full report", async () => {
    const fake = store()
      .on(`GET ${BASE}/incidents/${INCIDENT}`, incident())
      .on(`GET ${BASE}/investigations/${INVESTIGATION}/steps`, steps)
      .on(`GET ${BASE}/investigations/${INVESTIGATION}`, report)
      .on(`GET ${BASE}/decisions/${DECISION}`, decision("proposed"))
      .on(`GET ${BASE}/facts/21`, { fact: impact, formula: null, parents: [], sources: [] })
      .on(`GET ${BASE}/facts/22`, { fact: zero, formula: null, parents: [], sources: [] })
      .on(`POST ${BASE}/policy/preview`, {
        allowed: true,
        rule: "allowed",
        reason: "every rule passed",
        version: "v1",
      });
    renderApp("/", fake.api);
    await userEvent.click(await screen.findByRole("button", { name: "What I checked" }));
    const checked = await screen.findByRole("region", { name: "What I checked" });
    expect(within(checked).getByRole("heading", { name: "Here’s what I checked." })).toBeVisible();
    expect(await within(checked).findByText("Likely")).toBeInTheDocument();
    expect(
      within(checked).getByText("Ads keep spending on a product that is out of stock."),
    ).toBeVisible();
    expect(within(checked).getByText("Checked stock against lead time")).toBeVisible();
    const mySteps = within(checked).getByRole("button", { name: /^My steps/ });
    expect(mySteps).toHaveTextContent("My steps· took 41 s");
    await userEvent.click(mySteps);
    expect(within(checked).getByText("Checked the stock of Trail Jacket")).toBeVisible();
    await userEvent.click(within(checked).getByRole("button", { name: "Full report" }));
    expect(within(checked).getByText(/Spend kept going/)).toBeVisible();
    expect(within(checked).getByRole("button", { name: "$140, see the proof" })).toBeVisible();
    await userEvent.click(within(checked).getByRole("button", { name: "See options" }));
    // A decision opens where decisions live: the Decisions page, not the conversation.
    expect(await screen.findByRole("heading", { name: "Decisions", level: 1 })).toBeVisible();
  });

  it("can be started, and followed as it works", async () => {
    let done = false;
    const fake = store()
      .on(`GET ${BASE}/incidents/${INCIDENT}`, () =>
        json(incident(done ? {} : { investigation_ids: [], decision_ids: [] })),
      )
      .on(`POST ${BASE}/incidents/${INCIDENT}/investigations`, () =>
        json({ investigation_id: INVESTIGATION, events: "", result: "" }, 202),
      )
      .on(`GET ${BASE}/investigations/${INVESTIGATION}/events`, () => {
        done = true;
        return sse(["step", steps[1]], ["done", {}]);
      })
      .on(`GET ${BASE}/investigations/${INVESTIGATION}/steps`, steps)
      .on(`GET ${BASE}/investigations/${INVESTIGATION}`, report);
    renderApp("/", fake.api);
    await userEvent.click(await screen.findByRole("button", { name: "What I checked" }));
    await userEvent.click(await screen.findByRole("button", { name: "Investigate now" }));
    expect(await screen.findByText("Likely")).toBeInTheDocument();
  });

  it("says when it cannot start, or the problem cannot be read", async () => {
    const fake = store()
      .on(
        `GET ${BASE}/incidents/${INCIDENT}`,
        incident({ investigation_ids: [], decision_ids: [] }),
      )
      .on(`POST ${BASE}/incidents/${INCIDENT}/investigations`, () => problem(503, "down"));
    renderApp("/", fake.api);
    await userEvent.click(await screen.findByRole("button", { name: "What I checked" }));
    await userEvent.click(await screen.findByRole("button", { name: "Investigate now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not start");
  });

  it("says when the problem cannot be read", async () => {
    const fake = store().on(`GET ${BASE}/incidents/${INCIDENT}`, () => problem(404, "not_found"));
    renderApp("/", fake.api);
    await userEvent.click(await screen.findByRole("button", { name: "What I checked" }));
    expect(await screen.findByText("This problem could not be loaded.")).toBeInTheDocument();
  });
});
