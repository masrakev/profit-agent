import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ConversationProvider } from "./ConversationProvider";
import { useConversation } from "./context";
import { DecisionMessage } from "./DecisionMessage";
import { CAMPAIGN, DECISION, decision, impact, option, zero } from "@/test/conversation";
import { fakeApi, json, problem, type FakeApi } from "@/test/fakeApi";
import { mockSystemTheme } from "@/test/matchMedia";
import { renderInStore, STORE_ID } from "@/test/render";

const BASE = `/api/v1/stores/${STORE_ID}`;
const QUESTION = decision("proposed").label;
const PASSED = { allowed: true, rule: "allowed", reason: "every rule passed", version: "v1" };

beforeEach(() => {
  mockSystemTheme(false);
});

/** The decision, with what the owner opens from it below. */
function Opened() {
  const { messages } = useConversation();
  return messages.map((message) =>
    message.kind === "decision" ? (
      <DecisionMessage key={message.id} decisionId={message.decisionId} />
    ) : null,
  );
}

function api(body: unknown = decision("proposed")): FakeApi {
  return fakeApi()
    .on(`GET ${BASE}/decisions/${DECISION}`, body)
    .on(`GET ${BASE}/facts/21`, { fact: impact, formula: null, parents: [], sources: [] })
    .on(`GET ${BASE}/facts/22`, { fact: zero, formula: null, parents: [], sources: [] })
    .on(`POST ${BASE}/policy/preview`, PASSED);
}

function show(fake: FakeApi) {
  renderInStore(
    <ConversationProvider>
      <DecisionMessage decisionId={DECISION} />
      <Opened />
    </ConversationProvider>,
    fake.api,
  );
}

function action(summary: Record<string, unknown>) {
  return { id: "j1", kind: "action", at: "2026-11-02T10:00:00Z", summary };
}

describe("a decision in the conversation", () => {
  it("asks first: each option with its range, doing nothing, and the safety checks", async () => {
    const fake = api();
    show(fake);
    const card = await screen.findByRole("article", { name: QUESTION });
    expect(await within(card).findByText(/^Compared with doing nothing, Sep 15/)).toBeVisible();
    expect(await within(card).findByText("+$613 to +$654")).toBeVisible();
    expect(within(card).getByText("Do nothing")).toBeVisible();
    expect(within(card).getByText("$0")).toBeVisible();
    expect(
      await within(card).findByText(
        "Safety checks passed: within your limits · reversible · you can undo it anytime.",
      ),
    ).toBeVisible();
    const checked = fake.requests.find((r) => r.url.endsWith("/policy/preview"));
    expect(await checked?.json()).toEqual({
      kind: "pause_campaign",
      campaign_id: CAMPAIGN,
      change: "0",
    });
  });

  it("follows an approval live, to the state the platform reads back", async () => {
    let status = "proposed";
    const fake = api()
      .on(`GET ${BASE}/decisions/${DECISION}`, () => {
        const now = status;
        if (status === "executing") status = "executed";
        return json(decision(now));
      })
      .on(`POST ${BASE}/decisions/${DECISION}/approve`, () => {
        status = "executing";
        return json(decision("approved"));
      })
      .on(`GET ${BASE}/journal`, {
        items: [
          action({ decision_id: "other" }),
          action({
            decision_id: DECISION,
            provider: "meta",
            status: "succeeded",
            after: { status: "PAUSED" },
          }),
        ],
        next_cursor: null,
      });
    show(fake);
    const card = await screen.findByRole("article", { name: QUESTION });
    await within(card).findByText(/Safety checks passed/);
    await userEvent.click(within(card).getByRole("button", { name: "Approve" }));
    const approved = fake.requests.find((r) => r.url.endsWith("/approve"));
    expect(await approved?.json()).toEqual({ option_id: "pause" });
    const outcome = await screen.findByRole("article", {
      name: QUESTION,
    });
    expect(await within(outcome).findByText("Carrying it out")).toBeInTheDocument();
    expect(within(outcome).getByText(/You approved it/)).toBeVisible();
    expect(
      await within(outcome).findByText("Done", undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(await within(outcome).findByText("Meta Ads reports the campaign paused.")).toBeVisible();
    expect(within(outcome).getByRole("heading")).toHaveTextContent(
      "Pause ‘Trail Jacket — Prospecting’ until restock",
    );
  });

  it("changes nothing when the owner says not now", async () => {
    let status = "proposed";
    const fake = api()
      .on(`GET ${BASE}/decisions/${DECISION}`, () =>
        json(decision(status, { approved_option_id: null })),
      )
      .on(`POST ${BASE}/decisions/${DECISION}/reject`, () => {
        status = "rejected";
        return json(decision(status, { approved_option_id: null }));
      });
    show(fake);
    const card = await screen.findByRole("article", { name: QUESTION });
    await userEvent.click(within(card).getByRole("button", { name: "Not now" }));
    expect(await screen.findByText("Not now: nothing changed.")).toBeVisible();
  });

  it("cannot be approved when a safety check blocks it", async () => {
    const fake = api().on(`POST ${BASE}/policy/preview`, {
      allowed: false,
      rule: "campaign_state",
      reason: "the campaign is already paused",
    });
    show(fake);
    const card = await screen.findByRole("article", { name: QUESTION });
    expect(
      await within(card).findByText("Blocked by a safety check: the campaign is already paused."),
    ).toBeVisible();
    expect(within(card).getByRole("button", { name: "Approve" })).toBeDisabled();
  });

  it("says when nothing is changed for the owner, only prepared", async () => {
    show(
      api(
        decision("proposed", {
          recommended_option_id: "reorder",
          options: [option("reorder", "Prepare a reorder of Trail Jacket", null)],
        }),
      ),
    );
    expect(
      await screen.findByText(
        "Safety checks passed: within your limits · nothing is changed for you: it is prepared for you to carry out.",
      ),
    ).toBeVisible();
  });

  it("says why an answer could not be sent", async () => {
    let calls = 0;
    const fake = api().on(`POST ${BASE}/decisions/${DECISION}/approve`, () => {
      calls += 1;
      return calls === 1 ? problem(409, "superseded") : problem(500, "internal");
    });
    show(fake);
    const card = await screen.findByRole("article", { name: QUESTION });
    await within(card).findByText(/Safety checks passed/);
    await userEvent.click(within(card).getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A newer decision replaced this one.",
    );
    await userEvent.click(within(card).getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be sent");
  });

  it.each([
    ["expired", "This decision expired before it was decided."],
    ["already_decided", "This decision was already decided."],
    ["not_executable", "This option cannot be carried out automatically."],
  ])("says when it is %s", async (code, text) => {
    const fake = api().on(`POST ${BASE}/decisions/${DECISION}/reject`, () => problem(409, code));
    show(fake);
    const card = await screen.findByRole("article", { name: QUESTION });
    await userEvent.click(within(card).getByRole("button", { name: "Not now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("points to the decision that replaced it", async () => {
    const fake = api(
      decision("superseded", {
        approved_option_id: null,
        superseded_by: "d-2",
        superseded_reason: "a newer decision on fresher data",
      }),
    ).on(
      `GET ${BASE}/decisions/d-2`,
      decision("proposed", { decision_id: "d-2", label: "Lower the daily budget?" }),
    );
    show(fake);
    const old = await screen.findByRole("article", { name: QUESTION });
    expect(within(old).getByRole("status")).toHaveTextContent("Replaced");
    expect(
      within(old).getByText("Replaced by a newer decision: a newer decision on fresher data"),
    ).toBeVisible();
    await userEvent.click(
      within(old).getByRole("button", { name: "See the decision that replaced it" }),
    );
    expect(
      await screen.findByRole("article", { name: "Lower the daily budget?" }),
    ).toBeInTheDocument();
  });

  it.each([
    ["expired", "Nobody approved it in time: nothing changed."],
    ["superseded", "Replaced by a newer decision."],
  ])("says so when it %s", async (status, text) => {
    show(api(decision(status, { approved_option_id: null })));
    expect(await screen.findByText(text)).toBeVisible();
  });

  it("says when it failed, or nothing is recorded yet", async () => {
    let calls = 0;
    const fake = api(decision("failed")).on(`GET ${BASE}/journal`, () => {
      calls += 1;
      return json({
        items:
          calls === 1
            ? [action({ decision_id: DECISION, provider: "meta", error: "the token expired" })]
            : [],
        next_cursor: null,
      });
    });
    show(fake);
    expect(await screen.findByText("It could not be carried out: the token expired")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Could not be carried out");
  });

  it("reads back an action whose state is not known", async () => {
    show(
      api(decision("measured")).on(`GET ${BASE}/journal`, {
        items: [action({ decision_id: DECISION, provider: "google" })],
        next_cursor: null,
      }),
    );
    expect(await screen.findByText("The ad platform carried it out.")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Done and measured");
  });

  it("says when no action is recorded yet, or the decision cannot be read", async () => {
    show(api(decision("executed")).on(`GET ${BASE}/journal`, { items: [], next_cursor: null }));
    expect(await screen.findByText("No action has been recorded yet.")).toBeVisible();
  });

  it("says when the decision cannot be read", async () => {
    show(fakeApi().on(`GET ${BASE}/decisions/${DECISION}`, () => problem(404, "not_found")));
    expect(await screen.findByText("This decision could not be loaded.")).toBeVisible();
  });
});
