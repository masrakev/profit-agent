import { describe, expect, it } from "vitest";

import { formatDay, formatPeriod } from "./dates";
import { counted, humanize } from "./words";

describe("a fact's period", () => {
  it("ends on the last day it covers (the API's end is excluded)", () => {
    expect(formatPeriod("2026-09-23T00:00:00Z", "2026-09-28T00:00:00Z")).toBe(
      "Sep 23 – Sep 27, 2026",
    );
  });

  it("is one day when it covers one", () => {
    expect(formatPeriod("2026-09-14T00:00:00Z", "2026-09-15T00:00:00Z")).toBe("Sep 14, 2026");
  });

  it("names both years when it spans two", () => {
    expect(formatPeriod("2025-12-29T00:00:00Z", "2026-01-05T00:00:00Z")).toBe(
      "Dec 29, 2025 – Jan 4, 2026",
    );
  });

  it("is read in UTC, as the API writes it", () => {
    expect(formatPeriod("2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z")).toBe(
      "Sep 1 – Sep 7, 2026",
    );
  });

  it("names one day of the API's", () => {
    expect(formatDay("2026-09-23")).toBe("Sep 23, 2026");
    expect(formatDay("not a day")).toBe("not a day");
  });

  it("is nothing when unreadable or empty", () => {
    expect(formatPeriod("soon", "2026-09-08T00:00:00Z")).toBeNull();
    expect(formatPeriod("2026-09-08T00:00:00Z", "2026-09-08T00:00:00Z")).toBeNull();
  });
});

describe("words", () => {
  it("turns identifiers into words", () => {
    expect(humanize("order_lines")).toBe("Order lines");
    expect(humanize("pause_until_restock")).toBe("Pause until restock");
    expect(humanize("")).toBe("");
  });

  it("counts with the right noun", () => {
    expect(counted(1, "row")).toBe("1 row");
    expect(counted(12, "row")).toBe("12 rows");
    expect(counted(2, "day", "days")).toBe("2 days");
  });
});
