/**
 * Facts as the API serves them: every number on screen is one of these, shown by its `formatted`
 * text and opened in the proof sheet. The frontend never derives a number from them.
 */

import { useQuery } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";

export type Fact = Schemas["FactOut"];
export type FactDetail = Schemas["FactDetail"];

export interface Estimate {
  p10: string;
  p50: string;
  p90: string;
}

/** An estimate with its range (the bar), or null for an exact or undefined fact. */
export function estimateOf(fact: Fact): Estimate | null {
  if (fact.kind !== "estimate" || !isDefined(fact)) return null;
  const { p10, p50, p90 } = fact;
  return p10 != null && p50 != null && p90 != null ? { p10, p50, p90 } : null;
}

export function isDefined(fact: Fact): boolean {
  return fact.status === "defined";
}

export const factKey = (storeId: string, factId: number) => ["fact", storeId, factId] as const;

/** The proof of one fact: formula, version, parents and source rows (null until asked for). */
export function useFactDetail(storeId: string, factId: number | null) {
  const api = useApi();
  return useQuery({
    queryKey: factKey(storeId, factId ?? 0),
    enabled: factId !== null,
    staleTime: Infinity, // a fact never changes: recomputing one makes a new fact
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/facts/{fact_id}", {
          params: { path: { store_id: storeId, fact_id: factId ?? 0 } },
        }),
      ),
  });
}

/**
 * The low and high ends of an estimate's formatted range, as the API wrote them ("$570–$614": the
 * API joins P10 and P90 with an en dash). Null when the text is not such a range.
 */
export function rangeEnds(formatted: string): { low: string; high: string } | null {
  const [low, high, ...rest] = formatted.split("–");
  return low && high && rest.length === 0 ? { low, high } : null;
}

/** How an estimate was made, in words, from the API's method identifier. */
const METHODS: Record<string, string> = {
  twin_monte_carlo_v1: "simulated outcomes",
  synthetic_control_v2: "compared with a synthetic control",
  block_bootstrap_shapley_v1: "resampled from your history",
  goal_trend_block_bootstrap_v1: "resampled from your trend",
  ols_daily_normal_v1: "fitted to your daily trend",
  sum_of_quantiles_v1: "summed from the ranges below",
};

export function methodText(method: string | null | undefined): string | null {
  // A derived estimate names its operation first ("negated:block_bootstrap_shapley_v1").
  const base = method?.split(":").at(-1);
  if (!base) return null;
  return METHODS[base] ?? base.replace(/_v[0-9]+$/, "").replaceAll("_", " ");
}
