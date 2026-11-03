import { useCallback, useMemo, useReducer, useRef, useState, type ReactNode } from "react";

import { ConversationContext, type Conversation, type Topic, type Turn } from "./context";
import { extension, reduce, type AgentStep, type AskAnswer, type Message } from "./model";
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
 * The API keeps each answer in a conversation it names first (`conversation`): the next
 * question continues it, until a new one starts or a kept one is resumed.
 */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const { storeId } = useStore();
  const [messages, dispatch] = useReducer(reduce, []);
  const nextId = useRef(1);
  const opened = useRef(new Set<string>());
  const id = () => nextId.current++;
  const [conversationId, setConversationId] = useState<string | null>(null);
  // The conversation the next question goes into, as soon as the API names it.
  const continues = useRef<string | null>(null);
  const kept = useCallback((named: string | null) => {
    continues.current = named;
    setConversationId(named);
  }, []);

  const run = useCallback(
    async (
      questionId: number,
      answerId: number,
      open: () => Promise<ReadableStream<Uint8Array>>,
    ) => {
      try {
        let ended = false;
        for await (const event of readEvents(await open())) {
          if (event.event === "conversation") {
            const named = (event.data as { conversation_id?: unknown }).conversation_id;
            if (typeof named === "string") kept(named);
          } else if (event.event === "step") {
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
    [kept],
  );

  const start = useCallback(
    (
      text: string | null,
      via: "text" | "voice",
      open: () => Promise<ReadableStream<Uint8Array>>,
      about: string | null = null,
    ) => {
      const questionId = id();
      const answerId = id();
      dispatch({
        type: "add",
        message: {
          id: questionId,
          kind: "question",
          text,
          via,
          listening: via === "voice",
          about,
        },
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

  const [topic, setTopic] = useState<Topic | null>(null);

  // A question about a decision or a goal carries it: the agent reads it with its label first.
  const ask = useCallback(
    (question: string, about?: Topic | null) => {
      const subject = about === undefined ? topic : about;
      start(
        question,
        "text",
        () =>
          unwrap(
            api.POST("/api/v1/stores/{store_id}/ask/stream", {
              params: { path: { store_id: storeId } },
              body: {
                question,
                conversation_id: continues.current ?? undefined,
                topic: subject ?? undefined,
              },
              parseAs: "stream",
            }),
          ) as Promise<ReadableStream<Uint8Array>>,
        subject?.label ?? null,
      );
    },
    [api, storeId, start, topic],
  );

  const askByVoice = useCallback(
    (recording: Blob, about?: Topic | null) => {
      const subject = about === undefined ? topic : about;
      const form = new FormData();
      form.append("audio", recording, `question.${extension(recording.type)}`);
      if (continues.current) form.append("conversation_id", continues.current);
      if (subject) {
        form.append("topic_kind", subject.kind);
        form.append("topic_id", subject.id);
        form.append("topic_label", subject.label);
      }
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
        subject?.label ?? null,
      );
    },
    [api, storeId, start, topic],
  );

  const newConversation = useCallback(
    (about: Topic | null = null) => {
      dispatch({ type: "load", messages: [] });
      opened.current.clear();
      kept(null);
      setTopic(about);
    },
    [kept],
  );

  const resume = useCallback(
    (named: string, turns: Turn[]) => {
      const loaded = turns.flatMap((turn): Message[] => [
        {
          id: id(),
          kind: "question",
          text: turn.question,
          via: turn.via,
          listening: false,
          about: turn.topic?.label ?? null,
        },
        {
          id: id(),
          kind: "answer",
          status: "answered",
          steps: [],
          result: turn.answer,
          problem: null,
        },
      ]);
      dispatch({ type: "load", messages: loaded });
      opened.current.clear();
      kept(named);
      setTopic(null);
    },
    [kept],
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
    () => ({
      messages,
      conversationId,
      newConversation,
      resume,
      topic,
      setTopic,
      ask,
      askByVoice,
      openDecision,
      openInvestigation,
    }),
    [
      messages,
      conversationId,
      newConversation,
      resume,
      topic,
      ask,
      askByVoice,
      openDecision,
      openInvestigation,
    ],
  );
  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}
