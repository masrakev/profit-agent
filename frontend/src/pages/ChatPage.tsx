import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { AnswerMessage } from "@/conversation/AnswerMessage";
import { useConversation } from "@/conversation/context";
import { DecisionMessage } from "@/conversation/DecisionMessage";
import { InvestigationMessage } from "@/conversation/InvestigationMessage";
import type { Message } from "@/conversation/model";
import { localDay } from "@/format/dates";
import { useStore } from "@/stores/store";
import { Bubble } from "@/ui/Bubble";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";
import { EmptyState } from "@/ui/EmptyState";
import { Icon } from "@/ui/Icon";
import { Skeleton } from "@/ui/Skeleton";

/**
 * Conversations: the owner's questions and the agent's answers, with what they opened (what was
 * checked about a problem). Each conversation is kept and has its address: the history lists
 * them, the latest first, and one opened again continues where it stopped. The day itself is on
 * Home.
 */
export function ChatPage() {
  const { conversationId: addressed } = useParams();
  const { messages, conversationId, resume, newConversation } = useConversation();
  const navigate = useNavigate();
  const api = useApi();
  const { storeId } = useStore();
  const [history, setHistory] = useState(false);
  const last = useRef<HTMLDivElement>(null);
  const count = messages.length;

  // A kept conversation, opened at its address: read again, unless it is the one on screen.
  const stored = useQuery({
    queryKey: ["conversation", storeId, addressed],
    enabled: addressed !== undefined && addressed !== conversationId,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/conversations/{conversation_id}", {
          params: { path: { store_id: storeId, conversation_id: addressed ?? "" } },
        }),
      ),
  });
  // Read again once per visit to its address: a new conversation started from it stays new.
  const resumed = useRef<string | null>(null);
  useEffect(() => {
    if (addressed === undefined) resumed.current = null;
  }, [addressed]);
  useEffect(() => {
    const data = stored.data;
    if (
      data &&
      data.conversation_id === addressed &&
      data.conversation_id !== conversationId &&
      resumed.current !== addressed
    ) {
      resumed.current = addressed;
      resume(data.conversation_id, data.turns);
    }
  }, [stored.data, addressed, conversationId, resume]);
  // The conversation on screen, once the API names it, takes its address.
  useEffect(() => {
    if (conversationId && addressed === undefined) {
      void navigate(`/chat/${conversationId}`, { replace: true });
    }
  }, [conversationId, addressed, navigate]);

  useEffect(() => {
    if (count > 0) last.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [count]);

  const loading = addressed !== undefined && addressed !== conversationId && stored.isPending;

  return (
    <section aria-label="Conversation" className="flex flex-col gap-12">
      <div className="flex flex-col gap-4">
        <header className="flex items-center justify-between gap-3">
          <h1 className="text-small font-medium text-ink-muted">Conversations</h1>
          <span className="flex items-center gap-2">
            <Button
              variant="ghost"
              className="h-9 px-3 text-small"
              aria-expanded={history}
              aria-controls="conversation-history"
              onClick={() => {
                setHistory((open) => !open);
              }}
            >
              History
              <Icon
                name="chevron-up"
                size={16}
                className={cx("transition-transform duration-150", !history && "rotate-180")}
              />
            </Button>
            <Button
              variant="secondary"
              className="h-9 px-3 text-small sm:px-4"
              disabled={count === 0 && conversationId === null}
              onClick={() => {
                newConversation();
                setHistory(false);
                void navigate("/chat");
              }}
            >
              <Icon name="plus" size={16} />
              <span className="max-sm:sr-only">New conversation</span>
            </Button>
          </span>
        </header>
        {history && (
          <History
            current={addressed ?? conversationId}
            onPick={() => {
              setHistory(false);
            }}
          />
        )}
      </div>
      {loading && <Skeleton rows={3} />}
      {stored.isError && (
        <p className="text-body text-ink-muted">This conversation could not be loaded.</p>
      )}
      {count === 0 && !loading && !stored.isError && (
        <EmptyState title="Ask anything about your store.">
          I answer from your own data, and every number opens its proof. Start from a question
          below, or type or say your own.
        </EmptyState>
      )}
      {messages.map((message, index) => (
        <div key={message.id} ref={index === count - 1 ? last : undefined} className="scroll-mt-6">
          <MessageView message={message} />
        </div>
      ))}
    </section>
  );
}

/** The kept conversations, the one answered last first, each by its first question. */
function History({ current, onPick }: { current: string | null; onPick: () => void }) {
  const api = useApi();
  const { storeId, timezone } = useStore();
  const listed = useQuery({
    queryKey: ["conversations", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/conversations", {
          params: { path: { store_id: storeId } },
        }),
      ),
  });
  const items = listed.data?.items ?? [];
  return (
    <nav
      id="conversation-history"
      aria-label="Past conversations"
      className="flex flex-col border-t border-line"
    >
      {listed.isPending && <Skeleton rows={3} />}
      {listed.isError && (
        <p className="py-3 text-small text-ink-muted">The conversations could not be loaded.</p>
      )}
      {listed.data && items.length === 0 && (
        <p className="py-3 text-small text-ink-muted">
          No conversation kept yet: each question you ask starts one.
        </p>
      )}
      {items.length > 0 && (
        <ul className="flex flex-col">
          {items.map((c) => {
            const open = c.conversation_id === current;
            return (
              <li key={c.conversation_id} className="border-b border-line">
                <Link
                  to={`/chat/${c.conversation_id}`}
                  aria-current={open ? "page" : undefined}
                  onClick={onPick}
                  className={cx(
                    "-mx-3 flex items-baseline justify-between gap-4 rounded-md px-3 py-3 transition-colors duration-150",
                    open ? "bg-subtle" : "hover:bg-subtle/60",
                  )}
                >
                  <span className="min-w-0 truncate text-small text-ink">{c.title}</span>
                  <time className="shrink-0 font-mono text-label text-ink-muted">
                    {localDay(c.updated_at, timezone).label}
                  </time>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}

function MessageView({ message }: { message: Message }) {
  switch (message.kind) {
    case "question":
      return (
        <Bubble from="owner">
          {message.about && (
            <span className="mb-1 block text-label text-ink-muted">About {message.about}</span>
          )}
          {message.text ?? (
            <span className="text-ink-muted">
              {message.listening ? "Listening to your question…" : "Your recorded question"}
            </span>
          )}
        </Bubble>
      );
    case "answer":
      return (
        <AnswerMessage
          status={message.status}
          steps={message.steps}
          result={message.result}
          problem={message.problem}
        />
      );
    case "investigation":
      return <InvestigationMessage incidentId={message.incidentId} />;
    case "decision":
      return <DecisionMessage decisionId={message.decisionId} />;
  }
}
