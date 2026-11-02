import { useLocation, useNavigate } from "react-router";

import { useConversation } from "./context";

/**
 * Opening a decision or an investigation puts it in the conversation; from another page, the
 * owner is taken there to see it.
 */
export function useOpenInChat() {
  const { openDecision, openInvestigation } = useConversation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const there = () => {
    if (pathname !== "/") void navigate("/");
  };
  return {
    decision: (decisionId: string) => {
      openDecision(decisionId);
      there();
    },
    investigation: (incidentId: string) => {
      openInvestigation(incidentId);
      there();
    },
  };
}
