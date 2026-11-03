import { useQueries } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { factKey, type Fact } from "@/facts/facts";
import { useStore } from "@/stores/store";

type Decision = Schemas["DecisionView"];
export type Outcome = Decision["outcomes"][number];

/** Facts by id, each read once and kept (a fact never changes). */
export function useFacts(ids: (number | null | undefined)[]): Map<number, Fact> {
  const api = useApi();
  const { storeId } = useStore();
  const wanted = [...new Set(ids.flatMap((id) => (id == null ? [] : [id])))];
  const found = useQueries({
    queries: wanted.map((factId) => ({
      queryKey: factKey(storeId, factId),
      staleTime: Infinity,
      queryFn: () =>
        unwrap(
          api.GET("/api/v1/stores/{store_id}/facts/{fact_id}", {
            params: { path: { store_id: storeId, fact_id: factId } },
          }),
        ),
    })),
  });
  return new Map(
    found.flatMap((q) => (q.data ? [[q.data.fact.fact_id, q.data.fact] as const] : [])),
  );
}

/** Its latest measured outcome, else its latest one (an abstention says why). */
export function outcomeOf(d: Decision): Outcome | undefined {
  return d.outcomes.findLast((o) => o.status === "measured") ?? d.outcomes.at(-1);
}

/** The impact the decision expects: its chosen option's, or the recommended one's. */
export function predicted(d: Decision): number | null {
  const id = d.approved_option_id ?? d.recommended_option_id;
  return d.options.find((o) => o.option_id === id)?.impact_fact_id ?? null;
}

/** The facts a decision's row shows: what it expected, and what was measured. */
export function rowFacts(d: Decision): { expected: number | null; measured: number | null } {
  const o = outcomeOf(d);
  return { expected: o?.predicted_fact_id ?? predicted(d), measured: o?.effect_fact_id ?? null };
}
