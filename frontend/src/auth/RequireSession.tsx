import { useQuery } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { useSession } from "./session";
import { useApi } from "@/api/context";
import { ProofProvider } from "@/facts/ProofProvider";
import { fetchStore, StoreContext, storeKey, type StoreRef } from "@/stores/store";
import { Button } from "@/ui/Button";

/**
 * The gate of every signed-in page: without a session the owner is sent to sign in (and brought
 * back after); with one, the pages below get the store and the proof sheet.
 */
export function RequireSession() {
  const session = useSession();
  const location = useLocation();
  const api = useApi();
  const storeId = session.data?.store_ids[0];
  const info = useQuery({
    queryKey: storeKey(storeId ?? ""),
    queryFn: () => fetchStore(api, storeId ?? ""),
    enabled: storeId !== undefined,
    staleTime: 5 * 60_000,
  });
  const store = useMemo<StoreRef | null>(
    () =>
      storeId
        ? { storeId, name: info.data?.name ?? null, synthetic: info.data?.synthetic ?? false }
        : null,
    [storeId, info.data],
  );

  // The store's name is waited for (no flash of "Your store"), but never blocks the pages.
  if (session.isPending || (storeId && info.isPending)) {
    return <Notice busy>Opening your store…</Notice>;
  }
  if (session.isError) {
    return (
      <Notice>
        Your store could not be reached. Check your connection.
        <Button
          variant="secondary"
          onClick={() => {
            void session.refetch();
          }}
        >
          Try again
        </Button>
      </Notice>
    );
  }
  if (!session.data) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname + location.search }} />;
  }
  if (!store) return <Notice>No store is linked to this account yet.</Notice>;

  return (
    <StoreContext.Provider value={store}>
      <ProofProvider storeId={store.storeId}>
        <Outlet />
      </ProofProvider>
    </StoreContext.Provider>
  );
}

function Notice({ busy = false, children }: { busy?: boolean; children: ReactNode }) {
  return (
    <main
      aria-busy={busy}
      className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-canvas px-6 text-center text-body text-ink-muted"
    >
      {children}
    </main>
  );
}
