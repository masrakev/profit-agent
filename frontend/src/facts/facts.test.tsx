import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { estimateOf, isDefined, methodText, rangeEnds, useFactDetail } from "./facts";
import { estimate, exact } from "@/test/facts";
import { fakeApi } from "@/test/fakeApi";
import { renderHookWithApi } from "@/test/render";

const STORE = "ed68bb6d-1d14-5b04-af2b-e272de12e862";

describe("facts", () => {
  it("gives an estimate its range, never an exact or undefined fact", () => {
    expect(estimateOf(estimate)).toEqual({ p10: "5742.6200", p50: "6100.0000", p90: "6469.1100" });
    expect(estimateOf(exact)).toBeNull();
    const undefinedFact = { ...estimate, status: "undefined", undefined_reason: "no orders" };
    expect(estimateOf(undefinedFact)).toBeNull();
    expect(isDefined(undefinedFact)).toBe(false);
    expect(isDefined(exact)).toBe(true);
    expect(estimateOf({ ...estimate, p50: null })).toBeNull();
  });

  it("reads the ends of a range as the API formatted them", () => {
    expect(rangeEnds("$5,742.62–$6,469.11")).toEqual({ low: "$5,742.62", high: "$6,469.11" });
    expect(rangeEnds("-$20.00–$14.00")).toEqual({ low: "-$20.00", high: "$14.00" });
    expect(rangeEnds("$1,234.50")).toBeNull();
    expect(rangeEnds("a–b–c")).toBeNull();
    expect(rangeEnds("–$3")).toBeNull();
  });

  it("says how an estimate was made, in words", () => {
    expect(methodText("twin_monte_carlo_v1")).toBe("simulated outcomes");
    expect(methodText("negated:block_bootstrap_shapley_v1")).toBe("resampled from your history");
    expect(methodText("brand_new_method_v3")).toBe("brand new method");
    expect(methodText(null)).toBeNull();
    expect(methodText("")).toBeNull();
  });

  it("asks for a fact's proof only once one is opened", async () => {
    const detail = { fact: exact, formula: null, parents: [], sources: [] };
    const fake = fakeApi().on(`GET /api/v1/stores/${STORE}/facts/12`, detail);
    const closed = renderHookWithApi(() => useFactDetail(STORE, null), fake.api);
    expect(closed.result.current.fetchStatus).toBe("idle");
    const open = renderHookWithApi(() => useFactDetail(STORE, 12), fake.api);
    await waitFor(() => {
      expect(open.result.current.data).toEqual(detail);
    });
    expect(fake.requests).toHaveLength(1);
  });
});
