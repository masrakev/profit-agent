/**
 * The conversation, held by the client: the owner's questions (typed or said), the agent's
 * answers as they stream (its steps, then the answer contract), and the investigations and
 * decisions opened from the brief. The morning brief itself always comes first.
 */

import type { Schemas } from "@/api/client";

export type AskAnswer = Schemas["AskOut"];

/** One step of the agent's work, as the stream sends it. */
export interface AgentStep {
  kind: string; // started, model, tool, regeneration, answer, stopped, cache_hit, done, failed
  name: string | null;
  detail: Record<string, unknown>;
}

export type AnswerStatus = "working" | "answered" | "failed" | "no_speech";

export type Message =
  | {
      id: number;
      kind: "question";
      text: string | null; // a recorded question's, once heard
      via: "text" | "voice";
      listening: boolean; // a recorded question, until it is heard or the answer ends
      about?: string | null; // what it was asked about (a decision, a goal), by its label
    }
  | {
      id: number;
      kind: "answer";
      status: AnswerStatus;
      steps: AgentStep[];
      result: AskAnswer | null;
      problem: string | null;
    }
  | { id: number; kind: "investigation"; incidentId: string }
  | { id: number; kind: "decision"; decisionId: string };

export type Action =
  | { type: "add"; message: Message }
  | { type: "step"; id: number; step: AgentStep }
  | { type: "heard"; id: number; text: string }
  | { type: "listened"; id: number }
  | { type: "answered"; id: number; result: AskAnswer }
  | { type: "no_speech"; id: number }
  | { type: "failed"; id: number; problem: string };

export function reduce(messages: Message[], action: Action): Message[] {
  if (action.type === "add") return [...messages, action.message];
  return messages.map((message) => {
    if (message.id !== action.id) return message;
    if (message.kind === "question" && action.type === "heard") {
      return { ...message, text: action.text, listening: false };
    }
    if (message.kind === "question" && action.type === "listened") {
      return { ...message, listening: false };
    }
    if (message.kind !== "answer") return message;
    switch (action.type) {
      case "step":
        return { ...message, steps: [...message.steps, action.step] };
      case "answered":
        return { ...message, status: "answered", result: action.result };
      case "no_speech":
        return { ...message, status: "no_speech" };
      case "failed":
        return { ...message, status: "failed", problem: action.problem };
      default:
        return message;
    }
  });
}

/** The file name the server reads the format from: the recorder's container. */
export function extension(type: string): string {
  if (type.includes("mp4") || type.includes("aac")) return "m4a";
  if (type.includes("ogg")) return "ogg";
  if (type.includes("wav")) return "wav";
  return "webm";
}
