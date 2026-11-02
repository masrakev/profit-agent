import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { approvalToken } from "./token";
import { decision, option } from "@/test/conversation";
import { fakeApi, json, problem, type FakeApi } from "@/test/fakeApi";
import { mockSystemTheme } from "@/test/matchMedia";
import { renderApp } from "@/test/render";

const TOKEN = "eyJkIjoiZTgiLCJ2IjoiYSJ9.c2lnbmF0dXJlLXRoYXQtaXMtbG9uZw";
const LINK = `/api/v1/approval-links/${TOKEN}`;

beforeEach(() => {
  mockSystemTheme(false);
  window.history.replaceState(null, "", `/approve#token=${TOKEN}`);
});

function result(extra: Record<string, unknown> = {}) {
  return {
    decided: false,
    confirmation_required: false,
    option_id: "pause",
    verdict: "approved",
    decision: decision("proposed"),
    reason: null,
    ...extra,
  };
}

function open(fake: FakeApi) {
  renderApp("/approve", fake.api);
}

describe("the email approval page", () => {
  it("only shows what the link would decide, until the owner confirms", async () => {
    let decided = false;
    const fake = fakeApi()
      .on(`GET ${LINK}`, () => json(result()))
      .on(`POST ${LINK}`, () => {
        decided = true;
        return json(result({ decided: true, decision: decision("approved") }));
      });
    open(fake);
    expect(await screen.findByRole("heading", { name: "Approve this?" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Pause ‘Trail Jacket — Prospecting’ until restock?" }),
    ).toBeVisible();
    expect(screen.getByText(/carries it out within your spending caps/)).toBeVisible();
    expect(screen.getByText("The link works once, for this decision only.")).toBeVisible();
    expect(window.location.hash).toBe(""); // the token leaves the address bar
    expect(decided).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("heading", { name: "Approved" })).toBeVisible();
    expect(
      screen.getByText(/Pause ‘Trail Jacket — Prospecting’ until restock: it is being carried out/),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the app" })).toHaveAttribute("href", "/");
  });

  it("names the option when it is not the question itself", async () => {
    const fake = fakeApi().on(
      `GET ${LINK}`,
      result({
        option_id: "reorder",
        decision: decision("proposed", {
          options: [option("reorder", "Prepare a reorder of Trail Jacket", null)],
        }),
      }),
    );
    open(fake);
    expect(await screen.findByText("Prepare a reorder of Trail Jacket")).toBeVisible();
  });

  it("declines, which changes nothing", async () => {
    const fake = fakeApi()
      .on(`GET ${LINK}`, result({ verdict: "rejected" }))
      .on(`POST ${LINK}`, result({ decided: true, verdict: "rejected" }));
    open(fake);
    expect(await screen.findByRole("heading", { name: "Decline this?" })).toBeVisible();
    expect(screen.getByText("Declining changes nothing.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(await screen.findByRole("heading", { name: "Declined" })).toBeVisible();
    expect(screen.getByText(/Nothing changes/)).toBeVisible();
  });

  it("sends the owner to the app beyond the spending caps", async () => {
    open(fakeApi().on(`GET ${LINK}`, result({ confirmation_required: true })));
    expect(await screen.findByRole("note")).toHaveTextContent("beyond your spending caps");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByRole("link", { name: "Open the app" })).toBeVisible();
  });

  it.each([
    ["expired_link", 410, "This link has expired"],
    ["used_link", 409, "This link was already used"],
    ["superseded", 409, "Replaced by a newer decision"],
    ["already_decided", 409, "This decision was already decided"],
    ["expired", 409, "This decision has expired"],
    ["invalid_link", 403, "This link is not valid"],
  ])("says when the link is %s", async (code, status, title) => {
    open(fakeApi().on(`GET ${LINK}`, () => problem(status, code)));
    expect(await screen.findByRole("heading", { name: title })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the app" })).toBeVisible();
  });

  it("says when the link was used meanwhile", async () => {
    const fake = fakeApi()
      .on(`GET ${LINK}`, result())
      .on(`POST ${LINK}`, () => problem(409, "used_link"));
    open(fake);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(
      await screen.findByRole("heading", { name: "This link was already used" }),
    ).toBeVisible();
  });

  it("says when there is no token", async () => {
    window.history.replaceState(null, "", "/approve");
    open(fakeApi());
    expect(await screen.findByRole("heading", { name: "This link is not valid" })).toBeVisible();
  });
});

describe("the approval token", () => {
  it("is read from the fragment, and only when it looks like one", () => {
    expect(approvalToken(`#token=${TOKEN}`)).toBe(TOKEN);
    expect(approvalToken("#token=short")).toBeNull();
    expect(approvalToken("#token=has spaces in it, so not a token")).toBeNull();
    expect(approvalToken("")).toBeNull();
  });
});
