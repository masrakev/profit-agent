import { useCallback, useMemo, useReducer, useRef, type ReactNode } from "react";

import { ConversationContext, type Conversation } from "./context";
import { extension, reduce, type AgentStep, type AskAnswer } from "./model";
import { ApiError, unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { readEvents } from "@/api/sse";
import { useStore } from "@/stores/store";

const FAILED = "The answer could not be completed. Try asking again.";

function problemText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "audio_too_long") return "The recording is over two minutes.";
    if (error.code === "empty_audio") return "The recording is empty.";
    if (error.code === "unsupported_audio") return "This recording format cannot be read.";
    if (error.code === "conversion_unavailable") {
      return "Recordings cannot be heard on this server right now; type the question instead.";
    }
    if (error.status === 429) return "Too many questions at once. Wait a moment, then ask again.";
  }
  return FAILED;
}

/**
 * Holds the conversation for the signed-in pages, so it survives a visit to another page.
 * Questions stream their answers: each `step` is shown as it arrives, then `answer` (the answer
 * contract with the facts and names it cites); a recorded question first shows what was heard.
 */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const { storeId } = useStore();
  const [messages, dispatch] = useReducer(reduce, []);
  const nextId = useRef(1);
  const opened = useRef(new Set<string>());
  const id = () => nextId.current++;

  const run = useCallback(
    async (
      questionId: number,
      answerId: number,
      open: () => Promise<ReadableStream<Uint8Array>>,
    ) => {
      try {
        let ended = false;
        for await (const event of readEvents(await open())) {
          if (event.event === "step") {
            dispatch({ type: "step", id: answerId, step: event.data as AgentStep });
          } else if (event.event === "transcript") {
            const heard = event.data as { transcript?: unknown };
            if (typeof heard.transcript === "string" && heard.transcript) {
              dispatch({ type: "heard", id: questionId, text: heard.transcript });
            }
          } else if (event.event === "answer") {
            ended = true;
            dispatch({ type: "answered", id: answerId, result: event.data as AskAnswer });
          } else if (event.event === "no_speech") {
            ended = true;
            dispatch({ type: "no_speech", id: answerId });
          } else if (event.event === "failed") {
            ended = true;
            dispatch({ type: "failed", id: answerId, problem: FAILED });
          }
        }
        if (!ended) dispatch({ type: "failed", id: answerId, problem: FAILED });
      } catch (error) {
        dispatch({ type: "failed", id: answerId, problem: problemText(error) });
      } finally {
        dispatch({ type: "listened", id: questionId });
      }
    },
    [],
  );

  const start = useCallback(
    (
      text: string | null,
      via: "text" | "voice",
      open: () => Promise<ReadableStream<Uint8Array>>,
    ) => {
      const questionId = id();
      const answerId = id();
      dispatch({
        type: "add",
        message: { id: questionId, kind: "question", text, via, listening: via === "voice" },
      });
      dispatch({
        type: "add",
        message: {
          id: answerId,
          kind: "answer",
          status: "working",
          steps: [],
          result: null,
          problem: null,
        },
      });
      void run(questionId, answerId, open);
    },
    [run],
  );

  const ask = useCallback(
    (question: string) => {
      start(
        question,
        "text",
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
    [api, storeId, start],
  );

  const askByVoice = useCallback(
    (recording: Blob) => {
      const form = new FormData();
      form.append("audio", recording, `question.${extension(recording.type)}`);
      start(
        null,
        "voice",
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
    [api, storeId, start],
  );

  const openOnce = useCallback((key: string, add: (messageId: number) => void) => {
    if (opened.current.has(key)) return;
    opened.current.add(key);
    add(id());
  }, []);

  const openDecision = useCallback(
    (decisionId: string) => {
      openOnce(`decision:${decisionId}`, (messageId) => {
        dispatch({ type: "add", message: { id: messageId, kind: "decision", decisionId } });
      });
    },
    [openOnce],
  );

  const openInvestigation = useCallback(
    (incidentId: string) => {
      openOnce(`incident:${incidentId}`, (messageId) => {
        dispatch({ type: "add", message: { id: messageId, kind: "investigation", incidentId } });
      });
    },
    [openOnce],
  );

  const value = useMemo<Conversation>(
    () => ({ messages, ask, askByVoice, openDecision, openInvestigation }),
    [messages, ask, askByVoice, openDecision, openInvestigation],
  );
  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}
