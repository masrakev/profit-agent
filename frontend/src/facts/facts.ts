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
  if (fact.kind !== "estimate" || fact.status !== "ok") return null;
  const { p10, p50, p90 } = fact;
  return p10 != null && p50 != null && p90 != null ? { p10, p50, p90 } : null;
}

export function isUndefined(fact: Fact): boolean {
  return fact.status !== "ok";
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
