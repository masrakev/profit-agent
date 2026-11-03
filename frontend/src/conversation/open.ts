import { useLocation, useNavigate } from "react-router";

import { useConversation } from "./context";

/**
 * Where things open. A decision always opens on the Decisions page, its row expanded (everything
 * that asks the owner to decide lives there, not in the conversation). An investigation opens in
 * Conversations; from another page, the owner is taken there to see it.
 */
export function useOpen() {
  const { openInvestigation } = useConversation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return {
    decision: (decisionId: string) => {
      void navigate(`/decisions?open=${encodeURIComponent(decisionId)}`);
    },
    investigation: (incidentId: string) => {
      openInvestigation(incidentId);
      if (pathname !== "/chat") void navigate("/chat");
    },
  };
}
