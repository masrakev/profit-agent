import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

import { createMemoryRouter, RouterProvider } from "react-router";

import { fakeApi, type FakeApi } from "./fakeApi";
import type { Api } from "@/api/client";
import { ApiProvider } from "@/api/ApiProvider";
import { ProofProvider } from "@/facts/ProofProvider";
import { routes } from "@/router";
import { StoreContext } from "@/stores/store";
import { ThemeProvider } from "@/theme/ThemeProvider";

export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function wrapper(api: Api, queries: QueryClient) {
  return function Providers({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queries}>
        <ApiProvider api={api}>{children}</ApiProvider>
      </QueryClientProvider>
    );
  };
}

export function renderWithApi(
  ui: ReactElement,
  api: Api,
  options: RenderOptions & { queries?: QueryClient } = {},
) {
  const queries = options.queries ?? testQueryClient();
  return { queries, ...render(ui, { wrapper: wrapper(api, queries), ...options }) };
}

export function renderHookWithApi<T>(hook: () => T, api: Api, queries = testQueryClient()) {
  return { queries, ...renderHook(hook, { wrapper: wrapper(api, queries) }) };
}

export const STORE_ID = "ed68bb6d-1d14-5b04-af2b-e272de12e862";

export const SESSION = {
  kind: "session",
  actor: "owner:owner@example.com",
  store_ids: [STORE_ID],
  csrf_token: null,
  expires_at: "2026-12-02T00:00:00Z",
};

/** A signed-in store's fake API: the session and a ready platform; tests add their routes. */
export function signedInApi(): FakeApi {
  return fakeApi()
    .on("GET /api/v1/auth/session", SESSION)
    .on("GET /api/v1/ready", { status: "ready", database: "ok", schema_revision: null });
}

/** The whole app at `path`, on a memory router, with the theme and the given API. */
export function renderApp(path: string, api: Api, { dev = false }: { dev?: boolean } = {}) {
  const router = createMemoryRouter(routes(dev), { initialEntries: [path] });
  const result = renderWithApi(
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>,
    api,
  );
  return { router, ...result };
}

/** A component that uses the store and the proof sheet, as the signed-in pages do. */
export function renderInStore(ui: ReactElement, api: Api) {
  return renderWithApi(
    <StoreContext.Provider value={{ storeId: STORE_ID, name: null }}>
      <ProofProvider storeId={STORE_ID}>{ui}</ProofProvider>
    </StoreContext.Provider>,
    api,
  );
}
