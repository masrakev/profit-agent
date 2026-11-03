import { useEffect, useRef } from "react";

import { AnswerMessage } from "@/conversation/AnswerMessage";
import { useConversation } from "@/conversation/context";
import { DecisionMessage } from "@/conversation/DecisionMessage";
import { InvestigationMessage } from "@/conversation/InvestigationMessage";
import type { Message } from "@/conversation/model";
import { Bubble } from "@/ui/Bubble";
import { EmptyState } from "@/ui/EmptyState";

/**
 * Conversations: the owner's questions and the agent's answers, with what they opened (what was
 * checked about a problem). The day itself is on Home.
 */
export function ChatPage() {
  const { messages } = useConversation();
  const last = useRef<HTMLDivElement>(null);
  const count = messages.length;

  useEffect(() => {
    if (count > 0) last.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [count]);

  return (
    <section aria-label="Conversation" className="flex flex-col gap-12">
      <h1 className="sr-only">Conversations</h1>
      {count === 0 && (
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

function MessageView({ message }: { message: Message }) {
  switch (message.kind) {
    case "question":
      return (
        <Bubble from="owner">
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
