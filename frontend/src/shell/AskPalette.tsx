import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { Composer } from "./Composer";
import { Suggestions } from "./Suggestions";
import { useConversation, type Topic } from "@/conversation/context";
import { suggestedQuestions, useMorningBrief } from "@/conversation/morningBrief";
import { TOPIC_QUESTIONS } from "@/conversation/topics";
import { cx } from "@/ui/cx";
import { useDialog } from "@/ui/dialog";
import { Icon } from "@/ui/Icon";

/**
 * Ask from anywhere (⌘K or Ctrl+K, or Ask in the header): a question typed or said starts a new
 * conversation, about the decision or the goal on screen unless the owner turns that off, and
 * Conversations opens to follow the answer.
 */
export function AskPalette({ here, onClose }: { here: Topic | null; onClose: () => void }) {
  const { ask, askByVoice, newConversation } = useConversation();
  const { brief } = useMorningBrief();
  const navigate = useNavigate();
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const [aboutHere, setAboutHere] = useState(here !== null);
  useDialog(panel, onClose);
  // The field takes the focus: the palette is for typing a question.
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("textarea, input")?.focus();
  }, []);

  const about = aboutHere ? here : null;
  const begin = () => {
    newConversation(about);
    onClose();
    void navigate("/chat");
  };
  const typed = (question: string) => {
    begin();
    ask(question, about);
  };
  const said = (recording: Blob) => {
    begin();
    askByVoice(recording, about);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-scrim px-4 pt-16 sm:pt-24">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex w-full max-w-[640px] flex-col gap-4 rounded-card bg-surface p-5 shadow-sheet sm:p-6"
      >
        <div className="flex items-center justify-between gap-3">
          <h2 id={titleId} className="flex items-center gap-2 text-small font-medium text-ink">
            Ask
          </h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="-m-1 cursor-pointer rounded-full p-1 text-ink-muted hover:text-ink"
          >
            <Icon name="x" />
          </button>
        </div>
        {here && (
          <button
            type="button"
            aria-pressed={aboutHere}
            onClick={() => {
              setAboutHere((on) => !on);
            }}
            className={cx(
              "flex max-w-full cursor-pointer items-center gap-2 self-start rounded-full border py-1 pr-3 pl-2.5 text-small transition-colors duration-150",
              aboutHere
                ? "border-transparent bg-subtle text-ink"
                : "border-line text-ink-muted hover:text-ink",
            )}
          >
            <Icon name={aboutHere ? "circle-check" : "plus"} size={14} />
            <span className="shrink-0 text-ink-muted">About this {here.kind}</span>
            <span className="min-w-0 truncate font-medium">{here.label}</span>
          </button>
        )}
        <Composer onSend={typed} onVoice={said} />
        <Suggestions
          questions={about ? TOPIC_QUESTIONS[about.kind] : suggestedQuestions(brief)}
          onPick={typed}
        />
      </div>
    </div>
  );
}
