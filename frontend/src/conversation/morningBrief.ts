/** The morning brief's data, and the questions it suggests. */

import { useQuery } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { useStore } from "@/stores/store";

type Document = Schemas["DocumentOut"];

const ENTITY = /\{\{E:((?:product|campaign):[0-9a-f-]{36})\}\}/;

/** The latest daily brief: what the store's day looks like, as the morning email said it. */
export function useMorningBrief() {
  const api = useApi();
  const { storeId } = useStore();
  const store = { params: { path: { store_id: storeId } } };
  const list = useQuery({
    queryKey: ["briefings", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/briefings", {
          params: { path: { store_id: storeId }, query: { limit: 20 } },
        }),
      ),
  });
  const latest = list.data?.items.find((b) => b.kind === "daily");
  const brief = useQuery({
    queryKey: ["briefing", storeId, latest?.briefing_id],
    enabled: latest !== undefined,
    staleTime: Infinity, // a stored brief does not change
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/briefings/{briefing_id}", {
          params: { path: { ...store.params.path, briefing_id: latest?.briefing_id ?? "" } },
        }),
      ),
  });
  return {
    brief: brief.data,
    pending: list.isPending || (latest !== undefined && brief.isPending),
    none: list.isSuccess && latest === undefined,
    failed: list.isError || brief.isError,
  };
}

/**
 * Questions worth asking now, from the document's own situation: what it flags first, the
 * week's profit, the decisions waiting. Words only: the numbers stay in the answers.
 */
export function suggestedQuestions(document: Document | undefined): string[] {
  if (!document) return [];
  const section = (key: string) => document.sections.find((s) => s.key === key);
  const first = section("top_items")?.items[0];
  const ref = first ? ENTITY.exec(first.text)?.[1] : undefined;
  const name = ref ? document.names[ref] : undefined;
  const out = [
    ...(name ? [`What should I do about ${name}?`] : []),
    "What moved my net profit this week?",
    ...((section("pending_decisions")?.items.length ?? 0) > 0
      ? ["Which decision should I answer first?"]
      : []),
    "Where could I earn more next month?",
  ];
  return out.slice(0, 4);
}
