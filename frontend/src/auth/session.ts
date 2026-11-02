/**
 * Signing in with an email link (ADR 0020): the owner asks for a link, the email opens
 * `/sign-in#token=…`, and the page exchanges the token for a session (an HTTP-only cookie, plus
 * the readable CSRF cookie the client echoes). The token travels in the URL fragment, so it reaches
 * no server log; the page removes it from the address bar before exchanging it.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, unwrap, type Api, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";

export type Session = Schemas["SessionView"];

export const SESSION_KEY = ["session"] as const;

/** The current session, or null when nobody is signed in (a 401 is not an error here). */
export async function fetchSession(api: Api): Promise<Session | null> {
  try {
    return await unwrap(api.GET("/api/v1/auth/session"));
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function useSession() {
  const api = useApi();
  return useQuery({ queryKey: SESSION_KEY, queryFn: () => fetchSession(api) });
}

export function useRequestLink() {
  const api = useApi();
  return useMutation({
    mutationFn: (email: string) =>
      unwrap(api.POST("/api/v1/auth/magic-links", { body: { email } })),
  });
}

export async function openSession(api: Api, token: string): Promise<Session> {
  return unwrap(api.POST("/api/v1/auth/sessions", { body: { token } }));
}

export function useOpenSession() {
  const api = useApi();
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (token: string) => openSession(api, token),
    onSuccess: (session) => {
      queries.setQueryData(SESSION_KEY, session);
    },
  });
}

export function useSignOut() {
  const api = useApi();
  const queries = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/auth/session")),
    onSuccess: () => {
      queries.clear(); // nothing of the store stays in memory
      queries.setQueryData(SESSION_KEY, null);
    },
  });
}

/** The sign-in token in a link's fragment (`#token=…`), if any. */
export function tokenFromFragment(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("token");
  return token && /^[A-Za-z0-9_-]+$/.test(token) ? token : null;
}

/** Removes the fragment from the address bar and the history entry, keeping the path. */
export function clearFragment(location: Location = window.location): void {
  window.history.replaceState(window.history.state, "", location.pathname + location.search);
}
