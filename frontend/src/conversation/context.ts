import { createContext, useContext } from "react";

import type { Message } from "./model";

/** What the next questions are about: a decision or a goal, by its label. */
export interface Topic {
  kind: "decision" | "goal";
  id: string;
  label: string;
}

export interface Conversation {
  messages: Message[];
  /** What typed questions are about, until cleared; null for the store as a whole. */
  topic: Topic | null;
  setTopic: (topic: Topic | null) => void;
  /** Asks a typed question; the answer streams in below it. */
  ask: (question: string) => void;
  /** Asks a recorded question: its transcript appears first, then the answer. */
  askByVoice: (recording: Blob) => void;
  /** Shows a decision in the conversation (once: a second call does nothing). */
  openDecision: (decisionId: string) => void;
  /** Shows what was checked for an incident (once). */
  openInvestigation: (incidentId: string) => void;
}

export const ConversationContext = createContext<Conversation | null>(null);

export function useConversation(): Conversation {
  const conversation = useContext(ConversationContext);
  if (!conversation) throw new Error("useConversation needs a <ConversationProvider> above it");
  return conversation;
}
