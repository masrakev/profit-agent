import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("lets the last size, padding and height win", () => {
    expect(cn("h-10 px-5 text-body", "h-9 px-4 text-small")).toBe("h-9 px-4 text-small");
  });

  it("keeps a colour beside a size token, and a radius token apart from a colour", () => {
    expect(cn("text-body text-ink-muted", "text-small")).toBe("text-ink-muted text-small");
    expect(cn("rounded-full bg-surface", "rounded-card")).toBe("bg-surface rounded-card");
    expect(cn("shadow-md text-ink", "shadow-float")).toBe("text-ink shadow-float");
  });

  it("skips what a condition turned off", () => {
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
  });
});
