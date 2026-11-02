import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

import type { Api } from "@/api/client";
import { ApiProvider } from "@/api/ApiProvider";

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
