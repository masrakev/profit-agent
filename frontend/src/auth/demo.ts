import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { SESSION_KEY } from "./session";
import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";

/** Whether this server offers its demo store (a demo server): then anyone may explore it. */
export function useDemo() {
  const api = useApi();
  return useQuery({
    queryKey: ["demo"],
    queryFn: () => unwrap(api.GET("/api/v1/auth/demo")),
    retry: false,
    staleTime: Infinity,
  });
}

/** Opens the demo store as its owner, without an email: the demo server's own session. */
export function useOpenDemo() {
  const api = useApi();
  const queries = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/demo-session")),
    onSuccess: (session) => {
      queries.setQueryData(SESSION_KEY, session);
    },
  });
}
