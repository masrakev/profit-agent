import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BrandMark } from "./BrandMark";
import { Bubble } from "./Bubble";
import { Button } from "./Button";
import { cx } from "./cx";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";
import { BRAND } from "@/brand";

describe("the style guide's primitives", () => {
  it("joins only the classes that are on", () => {
    expect(cx("a", false, null, undefined, "b")).toBe("a b");
  });

  it("draws an icon as a mask at its Figma size, hidden from assistive technology", () => {
    const { container } = render(
      <>
        <Icon name="mic" />
        <Icon name="chevron-up" />
        <Icon name="circle-check" size={12} className="text-accent-ink" />
      </>,
    );
    const [mic, chevron, check] = Array.from(
      container.querySelectorAll<HTMLElement>("[data-icon]"),
    );
    expect(mic).toHaveAttribute("aria-hidden", "true");
    expect(mic?.style.width).toBe("20px");
    expect(mic?.style.maskImage).toContain("url(");
    expect(chevron?.style.height).toBe("16px");
    expect(check?.style.width).toBe("12px");
    expect(check).toHaveClass("bg-current", "text-accent-ink");
  });

  it("makes buttons that never submit a form by accident", () => {
    render(
      <>
        <Button>Approve</Button>
        <Button variant="danger" block>
          Delete store
        </Button>
        <Button type="submit" variant="ghost">
          Send
        </Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Approve" })).toHaveAttribute("type", "button");
    expect(screen.getByRole("button", { name: "Approve" })).toHaveClass("bg-accent-fill");
    expect(screen.getByRole("button", { name: "Delete store" })).toHaveClass("bg-danger", "w-full");
    expect(screen.getByRole("button", { name: "Send" })).toHaveAttribute("type", "submit");
  });

  it("says a status in words; the dot only echoes it", () => {
    const { container } = render(<StatusPill tone="warning">Watch</StatusPill>);
    expect(screen.getByText("Watch")).toBeInTheDocument();
    expect(container.querySelector("[data-tone=warning]")).toHaveAttribute("aria-hidden", "true");
  });

  it("names the product, visibly or for screen readers", () => {
    const { rerender } = render(<BrandMark />);
    expect(screen.getByText(BRAND.name)).toHaveClass("sr-only");
    rerender(<BrandMark named />);
    expect(screen.getByText(BRAND.name)).not.toHaveClass("sr-only");
  });

  it("shows merchant words as text, never as markup", () => {
    const { container } = render(<Bubble from="agent">{"<img src=x onerror=alert(1)>"}</Bubble>);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    render(<Bubble from="owner">Hi</Bubble>);
    expect(screen.getByText("Hi")).toHaveAttribute("data-from", "owner");
  });
});
