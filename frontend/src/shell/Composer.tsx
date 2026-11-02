import { useId, useState, type FormEvent } from "react";

import { Icon } from "@/ui/Icon";

interface ComposerProps {
  /** Sends a typed question; without it the composer is shown but cannot send yet. */
  onSend?: (text: string) => void;
  /** Starts a voice question. */
  onVoice?: () => void;
}

export const COMPOSER_PROMISE =
  "Your store. Your decisions. Nothing changes without your approval.";

/** Ask by text or by voice. Enter sends; the text is the owner's own, kept as plain text. */
export function Composer({ onSend, onVoice }: ComposerProps) {
  const [text, setText] = useState("");
  const inputId = useId();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const question = text.trim();
    if (!question || !onSend) return;
    onSend(question);
    setText("");
  };

  return (
    <div className="flex w-full flex-col gap-[9px]">
      <form
        onSubmit={submit}
        className="flex h-16 w-full items-center gap-4 rounded-card border border-line bg-surface px-5 shadow-float focus-within:border-accent"
      >
        <button
          type="button"
          disabled
          aria-label="Add to the question"
          className="inline-flex text-ink-muted disabled:cursor-default"
        >
          <Icon name="plus" />
        </button>
        <label htmlFor={inputId} className="sr-only">
          Ask anything about your store
        </label>
        <input
          id={inputId}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
          placeholder="Ask anything about your store…"
          autoComplete="off"
          enterKeyHint="send"
          maxLength={2000}
          className="min-w-0 flex-1 bg-transparent text-body text-ink outline-none placeholder:text-ink-muted"
        />
        <button
          type="button"
          onClick={onVoice}
          disabled={!onVoice}
          aria-label="Ask by voice"
          className="inline-flex cursor-pointer rounded-full text-ink-muted hover:text-ink disabled:cursor-default disabled:hover:text-ink-muted"
        >
          <Icon name="mic" />
        </button>
      </form>
      <p className="text-center text-caption text-ink-muted">{COMPOSER_PROMISE}</p>
    </div>
  );
}
