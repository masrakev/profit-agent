import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentMark } from "./AgentMark";
import { BrandMark } from "./BrandMark";
import { Bubble } from "./Bubble";
import { Button } from "./Button";
import { cx } from "./cx";
import { EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
import { Section } from "./Section";
import { Skeleton } from "./Skeleton";
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

  it("draws the agent's mark in its three states, as decoration", () => {
    const { container, rerender } = render(<AgentMark />);
    const mark = container.querySelector(".agent-mark");
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(mark).toHaveAttribute("data-state", "idle");
    rerender(<AgentMark state="working" />);
    expect(container.querySelector(".agent-mark")).toHaveAttribute("data-state", "working");
    rerender(<AgentMark state="waiting" size="lg" />);
    expect(container.querySelector(".agent-mark")).toHaveClass("size-8");
  });

  it("titles a section, says what is empty, and holds the place while loading", () => {
    render(
      <Section title="Steps" aside={<span>later</span>}>
        <p>content</p>
      </Section>,
    );
    expect(screen.getByRole("region", { name: "Steps" })).toHaveTextContent("content");
    render(<EmptyState title="No goal yet">Say one.</EmptyState>);
    expect(screen.getByText("No goal yet")).toBeInTheDocument();
    expect(screen.getByText("Say one.")).toBeInTheDocument();
    render(<Skeleton rows={2} />);
    expect(screen.getByLabelText("Loading")).toHaveAttribute("aria-busy", "true");
  });
});
