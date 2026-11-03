import { createContext, useContext } from "react";

import type { Schemas } from "@/api/client";

import type { Message } from "./model";

/** One kept question and its answer, as the API reads them again. */
export type Turn = Schemas["TurnOut"];

/** What the next questions are about: a decision or a goal, by its label. */
export interface Topic {
  kind: "decision" | "goal";
  id: string;
  label: string;
}

export interface Conversation {
  messages: Message[];
  /** The kept conversation the next question continues; null until the first is answered. */
  conversationId: string | null;
  /** Starts a new conversation, about a decision or a goal when one is given. */
  newConversation: (topic?: Topic | null) => void;
  /** Shows a kept conversation, read again, for the next question to continue. */
  resume: (conversationId: string, turns: Turn[]) => void;
  /** What typed questions are about, until cleared; null for the store as a whole. */
  topic: Topic | null;
  setTopic: (topic: Topic | null) => void;
  /** Asks a typed question (about `about`, else the current topic); the answer streams in. */
  ask: (question: string, about?: Topic | null) => void;
  /** Asks a recorded question: its transcript appears first, then the answer. */
  askByVoice: (recording: Blob, about?: Topic | null) => void;
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
