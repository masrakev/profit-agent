import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./client";

const MAX_RETRIES = 2;

/** Retry what may succeed later (network, 5xx); never a request the API refused (4xx). */
export function shouldRetry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && error.isClientError) return false;
  return failures < MAX_RETRIES;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}
