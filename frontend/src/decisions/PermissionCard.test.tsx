import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PermissionCard, type PermissionCardProps } from "./PermissionCard";
import { estimate } from "@/test/facts";
import { fakeApi } from "@/test/fakeApi";
import { renderInStore } from "@/test/render";

const cut = {
  ...estimate,
  fact_id: 14,
  formatted: "$150.00–$205.00",
  p10: "150",
  p50: "178",
  p90: "205",
};

function card(overrides: Partial<PermissionCardProps> = {}) {
  const props: PermissionCardProps = {
    question: "Pause ‘Trail Jacket — Prospecting’ until restock?",
    comparedWith: "Compared with doing nothing over 14 days",
    options: [
      { id: "pause", label: "Pause until restock", impact: estimate, recommended: true },
      { id: "cut", label: "Cut budget", impact: cut },
      { id: "reorder", label: "Prepare a reorder", impact: null },
    ],
    baseline: { label: "Do nothing", impact: null },
    safety: "Safety checks passed: within your limits · reversible.",
    onApprove: vi.fn(),
    onDecline: vi.fn(),
    ...overrides,
  };
  renderInStore(<PermissionCard {...props} />, fakeApi().api);
  return props;
}

describe("the permission card", () => {
  it("asks the question and shows every option with its range", () => {
    card();
    const article = screen.getByRole("article", {
      name: "Pause ‘Trail Jacket — Prospecting’ until restock?",
    });
    expect(within(article).getByText(/Pause until restock/)).toHaveTextContent(
      "Pause until restock $5,742.62–$6,469.11, see the proof (recommended)",
    );
    expect(within(article).getAllByText("Most likely")).toHaveLength(2);
    expect(within(article).getByText("Prepare a reorder")).toBeInTheDocument();
    expect(within(article).getByText("Do nothing")).toBeInTheDocument();
    expect(within(article).getByText(/Safety checks passed/)).toBeInTheDocument();
  });

  it("carries the Verified seal of its recommended option", async () => {
    card();
    await userEvent.click(screen.getByRole("button", { name: "Verified" }));
    await userEvent.click(screen.getByRole("button", { name: "See the proof" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("$5,742.62–$6,469.11");
  });

  it("opens each option's proof from its number", async () => {
    card();
    await userEvent.click(screen.getByRole("button", { name: "$150.00–$205.00, see the proof" }));
    expect(screen.getByRole("dialog", { name: "Cut budget" })).toBeInTheDocument();
  });

  it("folds its summary away and back", async () => {
    card();
    const summary = screen.getByRole("button", { name: "Summary" });
    expect(summary).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(summary);
    expect(summary).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Compared with doing nothing over 14 days")).not.toBeVisible();
    await userEvent.click(summary);
    expect(screen.getByText("Compared with doing nothing over 14 days")).toBeVisible();
  });

  it("passes the owner's answer on, and waits while it is sent", async () => {
    const props = card();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await userEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(props.onApprove).toHaveBeenCalledOnce();
    expect(props.onDecline).toHaveBeenCalledOnce();
  });

  it("disables both answers while one is in flight", () => {
    card({ pending: true, baseline: { label: "Do nothing", impact: cut } });
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Not now" })).toBeDisabled();
  });

  it("has no seal without a number", () => {
    card({ options: [{ id: "reorder", label: "Prepare a reorder", impact: null }] });
    expect(screen.queryByRole("button", { name: "Verified" })).toBeNull();
  });
});
