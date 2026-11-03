import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { useConversation } from "@/conversation/context";
import { useDecisions } from "@/decisions/useDecisions";
import { AgentMark, type AgentState } from "@/ui/AgentMark";

/**
 * The agent's status line, beside its mark, in three levels: working (it is answering a
 * question), waiting for the owner (a decision needs an answer: a link to them), or watching the
 * store. When the platform does not answer, that comes first.
 */
export function AgentStatus() {
  const api = useApi();
  const { messages } = useConversation();
  const ready = useQuery({
    queryKey: ["ready"],
    queryFn: () => unwrap(api.GET("/api/v1/ready")),
    refetchInterval: 60_000,
    retry: false,
  });
  const decisions = useDecisions();
  const waiting = (decisions.data?.items ?? []).some((d) => d.status === "proposed");
  const working = messages.some((m) => m.kind === "answer" && m.status === "working");

  let state: AgentState = "idle";
  let text = "Watching your store";
  if (ready.isPending) text = "Connecting…";
  else if (ready.isError) text = "Not connected";
  else if (working) {
    state = "working";
    text = "Working on your question";
  } else if (waiting) {
    state = "waiting";
    text = "Waiting for your decision";
  }

  const line = (
    <>
      <AgentMark state={state} size="sm" />
      <span className="truncate">{text}</span>
    </>
  );
  return (
    <span role="status" className="flex min-w-0 items-center gap-2 text-small text-ink-muted">
      {state === "waiting" ? (
        <Link to="/decisions" className="flex min-w-0 items-center gap-2 rounded-md hover:text-ink">
          {line}
        </Link>
      ) : (
        line
      )}
      {ready.isError && <span aria-hidden="true" className="size-1.5 rounded-full bg-danger" />}
    </span>
  );
}
