import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { readEvents } from "@/api/sse";
import { extension, type AskAnswer } from "@/conversation/model";
import { useStore } from "@/stores/store";

export type GoalAsk =
  | { state: "idle" }
  | { state: "working"; heard: string | null }
  | { state: "drafted"; goalId: string; heard: string | null }
  | { state: "not_a_goal"; heard: string | null }
  | { state: "failed"; heard: string | null };

/**
 * A goal said or typed, as Ask reads it: Ask restates a goal question as a draft goal and returns
 * its `goal_id`; the owner then confirms the restatement on the Goals page. Anything else is not a
 * goal, and belongs in the conversation.
 */
export function useGoalAsk() {
  const api = useApi();
  const queries = useQueryClient();
  const { storeId } = useStore();
  const [ask, setAsk] = useState<GoalAsk>({ state: "idle" });

  const run = useCallback(
    async (open: () => Promise<ReadableStream<Uint8Array>>) => {
      let heard: string | null = null;
      setAsk({ state: "working", heard });
      try {
        for await (const event of readEvents(await open())) {
          if (event.event === "transcript") {
            const said = (event.data as { transcript?: unknown }).transcript;
            if (typeof said === "string" && said) {
              heard = said;
              setAsk({ state: "working", heard });
            }
          } else if (event.event === "answer") {
            const goalId = (event.data as AskAnswer).goal_id;
            if (goalId) {
              await queries.invalidateQueries({ queryKey: ["goals", storeId] });
              setAsk({ state: "drafted", goalId, heard });
            } else {
              setAsk({ state: "not_a_goal", heard });
            }
            return;
          } else if (event.event === "no_speech" || event.event === "failed") {
            break;
          }
        }
        setAsk({ state: "failed", heard });
      } catch {
        setAsk({ state: "failed", heard });
      }
    },
    [queries, storeId],
  );

  const byText = useCallback(
    (question: string) => {
      void run(
        () =>
          unwrap(
            api.POST("/api/v1/stores/{store_id}/ask/stream", {
              params: { path: { store_id: storeId } },
              body: { question },
              parseAs: "stream",
            }),
          ) as Promise<ReadableStream<Uint8Array>>,
      );
    },
    [api, run, storeId],
  );

  const byVoice = useCallback(
    (recording: Blob) => {
      const form = new FormData();
      form.append("audio", recording, `goal.${extension(recording.type)}`);
      void run(
        () =>
          unwrap(
            api.POST("/api/v1/stores/{store_id}/ask/voice", {
              params: { path: { store_id: storeId } },
              body: form as unknown as { audio: string },
              parseAs: "stream",
            }),
          ) as Promise<ReadableStream<Uint8Array>>,
      );
    },
    [api, run, storeId],
  );

  return { ask, byText, byVoice };
}
