import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RangeBar } from "./RangeBar";
import { estimate, exact } from "@/test/facts";
import { fakeApi } from "@/test/fakeApi";
import { renderInStore } from "@/test/render";

describe("the range bar", () => {
  it("shows the ends as the API formatted them and marks the most likely value", () => {
    const { container } = renderInStore(<RangeBar fact={estimate} />, fakeApi().api);
    expect(screen.getByText("$5,742.62")).toBeInTheDocument();
    expect(screen.getByText("$6,469.11")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();
    expect(screen.getByText("Most likely")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    const at = (part: string) =>
      container.querySelector<HTMLElement>(`[data-part=${part}]`)?.style.left;
    expect(at("low")).toBe("0%");
    expect(at("high")).toBe("100%");
    const mark = Number.parseFloat(at("likely") ?? "");
    expect(mark).toBeGreaterThan(0);
    expect(mark).toBeLessThan(100);
  });

  it("opens the estimate's proof", async () => {
    renderInStore(<RangeBar fact={estimate} title="Money at stake" />, fakeApi().api);
    await userEvent.click(
      screen.getByRole("button", { name: "$5,742.62 to $6,469.11, see the proof" }),
    );
    expect(screen.getByRole("dialog", { name: "Money at stake" })).toBeInTheDocument();
  });

  it("is a plain picture where it is the proof itself", () => {
    renderInStore(<RangeBar fact={estimate} interactive={false} />, fakeApi().api);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Most likely")).toBeInTheDocument();
  });

  it("falls back to the formatted text when there is no usable range", () => {
    renderInStore(<RangeBar fact={exact} />, fakeApi().api);
    expect(screen.getByText("$1,234.50")).toBeInTheDocument();
    expect(screen.queryByText("Most likely")).toBeNull();
    renderInStore(<RangeBar fact={{ ...estimate, p50: "not a number" }} />, fakeApi().api);
    expect(screen.getByText("$5,742.62–$6,469.11")).toBeInTheDocument();
  });
});
