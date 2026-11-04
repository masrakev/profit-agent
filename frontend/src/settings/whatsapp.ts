import { useQuery } from "@tanstack/react-query";

import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { useStore } from "@/stores/store";

/** The owner's WhatsApp number: whether it is verified, as the API reads it. */
export function useWhatsAppNumber() {
  const api = useApi();
  const { storeId } = useStore();
  return useQuery({
    queryKey: ["whatsapp", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/whatsapp", {
          params: { path: { store_id: storeId } },
        }),
      ),
  });
}
