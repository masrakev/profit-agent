import { useEffect, useRef } from "react";

import { AnswerMessage } from "@/conversation/AnswerMessage";
import { Brief } from "@/conversation/Brief";
import { useConversation } from "@/conversation/context";
import { DecisionMessage } from "@/conversation/DecisionMessage";
import { InvestigationMessage } from "@/conversation/InvestigationMessage";
import type { Message } from "@/conversation/model";
import { Bubble } from "@/ui/Bubble";

/** The conversation: the morning brief, then the owner's questions and what they opened. */
export function ChatPage() {
  const { messages } = useConversation();
  const last = useRef<HTMLDivElement>(null);
  const count = messages.length;

  useEffect(() => {
    if (count > 0) last.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [count]);

  return (
    <section aria-label="Conversation" className="flex flex-col gap-8">
      <h1 className="sr-only">Chat</h1>
      <Brief />
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
              {message.via === "voice" ? "Listening to your question…" : "…"}
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
