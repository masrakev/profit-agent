import type { Tone } from "@/ui/StatusPill";

/** A decision's status in words, with the tone of its pill. */
export const STATUS: Record<string, { tone: Tone; text: string }> = {
  proposed: { tone: "warning", text: "Waiting for you" },
  approved: { tone: "info", text: "Approved: starting" },
  executing: { tone: "info", text: "Carrying it out" },
  executed: { tone: "good", text: "Done" },
  measured: { tone: "good", text: "Done and measured" },
  failed: { tone: "critical", text: "Could not be carried out" },
  rejected: { tone: "neutral", text: "Not now" },
  expired: { tone: "neutral", text: "Expired" },
  superseded: { tone: "neutral", text: "Replaced" },
};

export function statusOf(status: string): { tone: Tone; text: string } {
  return STATUS[status] ?? { tone: "neutral", text: status };
}

/** Where a decision came from, in words. */
export const SOURCES: Record<string, string> = {
  incident: "From an alert",
  goal: "From your goal’s plan",
  owner: "You asked",
};
