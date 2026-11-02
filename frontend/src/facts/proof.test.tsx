import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { FactValue } from "./FactValue";
import { useProof } from "./proofContext";
import { SEAL_TEXT, VerifiedSeal } from "./VerifiedSeal";
import { estimate, exact } from "@/test/facts";
import { fakeApi, json, problem } from "@/test/fakeApi";
import { renderInStore, renderWithApi, STORE_ID } from "@/test/render";

const FACTS = `/api/v1/stores/${STORE_ID}/facts`;

const parent = {
  ...exact,
  fact_id: 7,
  metric: "revenue",
  formatted: "$3,000.00",
  display: "$3,000",
};

const exactDetail = {
  fact: exact,
  formula: {
    formula_id: "net_profit",
    version: 3,
    description: "contribution_after_ads − fixed_costs",
    explanation: "Revenue minus every cost of the period",
    inputs: ["revenue", "costs"],
  },
  parents: [{ role: "revenue", fact: parent }],
  sources: [{ table: "order_lines", count: 12, ids: [] }],
};

function api() {
  return fakeApi()
    .on(`GET ${FACTS}/12`, exactDetail)
    .on(`GET ${FACTS}/13`, { fact: estimate, formula: null, parents: [], sources: [] })
    .on(`GET ${FACTS}/7`, {
      fact: parent,
      formula: null,
      parents: [],
      sources: [{ table: "orders", count: 1, ids: [] }],
    });
}

describe("a number on screen", () => {
  it("is the API's formatted text, and a button that opens its proof", async () => {
    renderInStore(<FactValue fact={exact} />, api().api);
    const number = screen.getByRole("button", { name: "$1,235, see the proof" });
    expect(number).toHaveAttribute("aria-haspopup", "dialog");
    await userEvent.click(number);
    const sheet = screen.getByRole("dialog", { name: "Net profit" });
    expect(within(sheet).getByText("$1,234.50")).toBeInTheDocument();
    expect(within(sheet).getByText("Exact · computed from your data")).toBeInTheDocument();
  });

  it("needs the proof sheet above it", () => {
    function Lost() {
      useProof();
      return null;
    }
    expect(() => renderWithApi(<Lost />, fakeApi().api)).toThrow("ProofProvider");
  });
});

describe("the proof sheet", () => {
  it("shows the formula and version, the period, what it is built from and its sources", async () => {
    renderInStore(<FactValue fact={exact} title="Profit this week" />, api().api);
    await userEvent.click(screen.getByRole("button"));
    const sheet = screen.getByRole("dialog", { name: "Profit this week" });
    expect(await within(sheet).findByText("Revenue minus every cost of the period")).toBeVisible();
    expect(within(sheet).getByText("How it’s calculated")).toBeInTheDocument();
    expect(within(sheet).getByText("Sep 1 – Sep 7, 2026")).toBeInTheDocument();
    expect(within(sheet).getByText("net_profit · version 3")).toBeInTheDocument();
    expect(within(sheet).getByText("contribution_after_ads − fixed_costs")).toBeInTheDocument();
    expect(within(sheet).getByText("Order lines")).toBeInTheDocument();
    expect(within(sheet).getByText("12 rows")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "$3,000, see the proof" })).toBeVisible();
  });

  it("lists a source's rows by date, a page at a time, with their total", async () => {
    const spend = { ...exact, fact_id: 21, metric: "ad_spend", formatted: "$412.40" };
    const row = (id: string, day: string, amount: string) => ({
      id,
      day,
      amount: { formatted: amount, display: amount },
    });
    const fake = fakeApi()
      .on(`GET ${FACTS}/21`, {
        fact: spend,
        formula: null,
        parents: [],
        sources: [
          {
            table: "ad_metrics_daily",
            source: "Meta Ads · Daily spend",
            data_up_to: "2026-09-14",
            count: 3,
            ids: [],
          },
        ],
      })
      .on(`GET ${FACTS}/21/rows`, (request: Request) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        return json(
          cursor
            ? { items: [row("c", "2026-09-25", "$79.85")], next_cursor: null }
            : {
                items: [row("a", "2026-09-23", "$76.20"), row("b", "2026-09-24", "$83.10")],
                next_cursor: "page-2",
              },
        );
      });
    renderInStore(<FactValue fact={spend} />, fake.api);
    await userEvent.click(screen.getByRole("button"));
    const sheet = screen.getByRole("dialog");
    expect(await within(sheet).findByText("Sep 23, 2026")).toBeInTheDocument();
    expect(within(sheet).getByText("Meta Ads · Daily spend")).toBeInTheDocument();
    expect(within(sheet).getByText("$83.10")).toBeInTheDocument();
    expect(within(sheet).getByText("Data up to Sep 14, 2026")).toBeInTheDocument();
    expect(within(sheet).queryByText("Total")).toBeNull();
    await userEvent.click(within(sheet).getByRole("button", { name: "Show more rows" }));
    expect(await within(sheet).findByText("$79.85")).toBeInTheDocument();
    expect(within(sheet).getByText("Total").parentElement).toHaveTextContent("$412.40");
    expect(fake.requests.at(-1)?.url).toContain("cursor=page-2");
  });

  it("opens a parent's proof on top, and goes back to the first", async () => {
    renderInStore(<FactValue fact={exact} />, api().api);
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(await screen.findByRole("button", { name: "$3,000, see the proof" }));
    const parentSheet = screen.getByRole("dialog", { name: "Revenue" });
    expect(await within(parentSheet).findByText("1 row")).toBeInTheDocument();
    await userEvent.click(within(parentSheet).getByRole("button", { name: "Back" }));
    expect(screen.getByRole("dialog", { name: "Net profit" })).toBeInTheDocument();
  });

  it("shows an estimate as its range, with how it was made", async () => {
    renderInStore(<FactValue fact={estimate} />, api().api);
    await userEvent.click(screen.getByRole("button"));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByText("Estimate · simulated by the store twin")).toBeInTheDocument();
    expect(within(sheet).getByText("$5,742.62 · $6,100.00 · $6,469.11")).toBeInTheDocument();
    expect(within(sheet).getByText("How it’s estimated")).toBeInTheDocument();
    expect(within(sheet).getByText("$5,742.62")).toBeInTheDocument();
    expect(within(sheet).getByText("Most likely")).toBeInTheDocument();
    expect(within(sheet).getByText(/a range, not a promise/)).toBeInTheDocument();
    expect(
      await within(sheet).findByText("Read from your data, without a formula."),
    ).toBeInTheDocument();
  });

  it("says a fact without a formula is derived when it has parents", async () => {
    const fake = fakeApi().on(`GET ${FACTS}/13`, {
      fact: estimate,
      formula: null,
      parents: [{ role: "impact", fact: parent }],
      sources: [],
    });
    renderInStore(<FactValue fact={estimate} />, fake.api);
    await userEvent.click(screen.getByRole("button"));
    expect(
      await screen.findByText("Derived from the facts it is built from, below."),
    ).toBeInTheDocument();
  });

  it("says why a number could not be computed", async () => {
    const undefinedFact = {
      ...exact,
      status: "undefined",
      formatted: "n/a",
      undefined_reason: "no_orders",
    };
    renderInStore(<FactValue fact={undefinedFact} />, api().api);
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Not computable · No orders")).toBeInTheDocument();
  });

  it("says so when the proof cannot be loaded", async () => {
    const fake = fakeApi().on(`GET ${FACTS}/12`, () => problem(503, "not_ready"));
    renderInStore(<FactValue fact={exact} />, fake.api);
    await userEvent.click(screen.getByRole("button"));
    expect(await screen.findByText("The proof could not be loaded.")).toBeInTheDocument();
  });

  it("is a modal: focus moves in and stays in, Escape closes and focus returns", async () => {
    renderInStore(<FactValue fact={exact} />, api().api);
    const number = screen.getByRole("button");
    await userEvent.click(number);
    const close = screen.getByRole("button", { name: "Close the proof" });
    expect(close).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    await userEvent.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    await userEvent.tab();
    expect(close).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(number).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes from its buttons and from a click outside", async () => {
    renderInStore(<FactValue fact={exact} />, api().api);
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(screen.getByRole("button", { name: "Close the proof" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(screen.getByRole("button"));
    await userEvent.click(document.body);
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });
});

describe("the Verified seal", () => {
  it("opens a note on how the numbers were made, with the proof one click away", async () => {
    renderInStore(<VerifiedSeal fact={estimate} title="Money at stake" />, api().api);
    const seal = screen.getByRole("button", { name: "Verified" });
    expect(screen.getByText(SEAL_TEXT)).not.toBeVisible();
    await userEvent.click(seal);
    expect(seal).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(SEAL_TEXT)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "See the proof" }));
    expect(screen.getByRole("dialog", { name: "Money at stake" })).toBeInTheDocument();
    expect(seal).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on Escape, giving focus back, and on a click elsewhere", async () => {
    renderInStore(<VerifiedSeal fact={exact} />, api().api);
    const seal = screen.getByRole("button", { name: "Verified" });
    await userEvent.click(seal);
    await userEvent.keyboard("{Escape}");
    expect(seal).toHaveAttribute("aria-expanded", "false");
    expect(seal).toHaveFocus();
    await userEvent.click(seal);
    await userEvent.click(document.body);
    expect(seal).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(seal);
    await userEvent.keyboard("a");
    expect(seal).toHaveAttribute("aria-expanded", "true");
  });
});
