import { waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { estimateOf, isDefined, quantileTexts, useFactDetail } from "./facts";
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

  it("gives an estimate's quantiles as the API wrote them, short or exact", () => {
    expect(quantileTexts(estimate)).toEqual({ p10: "$5,743", p50: "$6,100", p90: "$6,469" });
    expect(quantileTexts(estimate, "exact")).toEqual({
      p10: "$5,742.62",
      p50: "$6,100.00",
      p90: "$6,469.11",
    });
    expect(quantileTexts(exact)).toBeNull();
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
