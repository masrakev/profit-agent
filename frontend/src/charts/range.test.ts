import { describe, expect, it } from "vitest";

import { rangeGeometry, sharedDomain } from "./range";

describe("rangeGeometry", () => {
  it("places the P50 mark on a bar spanning P10 to P90", () => {
    expect(rangeGeometry("100.0000", "150.0000", "300.0000")).toEqual({
      low: 0,
      mark: 0.25,
      high: 1,
    });
  });

  it("places ranges on a shared axis", () => {
    expect(rangeGeometry("-50", "0", "50", { min: "-100", max: "100" })).toEqual({
      low: 0.25,
      mark: 0.5,
      high: 0.75,
    });
  });

  it("centres a range of zero width, and keeps marks on the axis", () => {
    expect(rangeGeometry("5", "5", "5")).toEqual({ low: 0.5, mark: 0.5, high: 0.5 });
    expect(rangeGeometry("0", "10", "20", { min: "5", max: "15" })).toEqual({
      low: 0,
      mark: 0.5,
      high: 1,
    });
  });

  it("draws no bar for values that are not numbers or out of order", () => {
    expect(rangeGeometry("n/a", "1", "2")).toBeNull();
    expect(rangeGeometry("3", "2", "1")).toBeNull();
    expect(rangeGeometry("1", "2", "3", { min: "9", max: "0" })).toBeNull();
  });
});

describe("sharedDomain", () => {
  it("spans the lowest P10 to the highest P90, as the API wrote them", () => {
    expect(
      sharedDomain([
        { p10: "-20.5000", p90: "40" },
        { p10: "-35.0000", p90: "10" },
      ]),
    ).toEqual({ min: "-35.0000", max: "40" });
    expect(sharedDomain([])).toBeNull();
    expect(sharedDomain([{ p10: "x", p90: "y" }])).toBeNull();
  });
});
