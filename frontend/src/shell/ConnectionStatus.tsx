import { useQuery } from "@tanstack/react-query";

import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { StatusPill } from "@/ui/StatusPill";

/**
 * Whether the platform answers, from the API's readiness check (polled each minute). The API has
 * no per-connection health yet (Shopify, Meta Ads), so this says "Connected", not "All systems".
 */
export function ConnectionStatus() {
  const api = useApi();
  const ready = useQuery({
    queryKey: ["ready"],
    queryFn: () => unwrap(api.GET("/api/v1/ready")),
    refetchInterval: 60_000,
    retry: false,
  });
  return (
    <span role="status">
      {ready.isPending ? (
        <StatusPill tone="neutral">Connecting…</StatusPill>
      ) : ready.isError ? (
        <StatusPill tone="critical">Not connected</StatusPill>
      ) : (
        <StatusPill tone="good">Connected</StatusPill>
      )}
    </span>
  );
}
