import { useQuery } from "@tanstack/react-query";

import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { useStore } from "@/stores/store";

/** The store's decisions, newest first (one query, shared by every page that lists them). */
export function useDecisions() {
  const api = useApi();
  const { storeId } = useStore();
  return useQuery({
    queryKey: ["decisions", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/decisions", {
          params: { path: { store_id: storeId }, query: { limit: 200 } },
        }),
      ),
  });
}
