import { useLocation, useNavigate } from "react-router";

import { useConversation, type Topic } from "./context";

/**
 * Where things open. A decision always opens on the Decisions page, at its own address (everything
 * that asks the owner to decide lives there, not in the conversation). An investigation opens in
 * Conversations; from another page, the owner is taken there to see it.
 */
export function useOpen() {
  const { openInvestigation, setTopic } = useConversation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return {
    decision: (decisionId: string) => {
      void navigate(`/decisions/${encodeURIComponent(decisionId)}`);
    },
    investigation: (incidentId: string) => {
      openInvestigation(incidentId);
      if (pathname !== "/chat") void navigate("/chat");
    },
    /** A conversation about a decision or a goal: its questions carry it. */
    ask: (topic: Topic) => {
      setTopic(topic);
      void navigate("/chat");
    },
  };
}
