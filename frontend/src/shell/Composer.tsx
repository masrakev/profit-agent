import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { Waveform } from "@/charts/Waveform";
import { Icon } from "@/ui/Icon";
import { createRecorder, MAX_SECONDS, type Recorder, type RecorderFactory } from "@/voice/recorder";

interface ComposerProps {
  /** Sends a typed question; without it the composer is shown but cannot send yet. */
  onSend?: (text: string) => void;
  /** Sends a recorded question; without it the microphone is off. */
  onVoice?: (recording: Blob) => void;
  /** Makes the recorder (tests give a fake one). */
  recorder?: RecorderFactory;
}

export const COMPOSER_PROMISE =
  "Your store. Your decisions. Nothing changes without your approval.";

type Mode = "typing" | "starting" | "recording";

/**
 * Ask by text or by voice. Enter sends the typed question. The microphone records a spoken one,
 * with its waveform while it records; Send sends it, Cancel drops it; it stops by itself at two
 * minutes. What the owner typed or said is theirs, kept as plain text.
 */
export function Composer({ onSend, onVoice, recorder = createRecorder }: ComposerProps) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<Mode>("typing");
  const [problem, setProblem] = useState<string | null>(null);
  const active = useRef<Recorder | null>(null);
  const limit = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputId = useId();

  useEffect(
    () => () => {
      active.current?.cancel();
      if (limit.current) clearTimeout(limit.current);
    },
    [],
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const question = text.trim();
    if (!question || !onSend) return;
    onSend(question);
    setText("");
  };

  const finish = async (send: boolean) => {
    const current = active.current;
    active.current = null;
    if (limit.current) clearTimeout(limit.current);
    setMode("typing");
    if (!current) return;
    if (!send) {
      current.cancel();
      return;
    }
    const recording = await current.stop();
    if (recording.size > 0) onVoice?.(recording);
  };

  const record = async () => {
    setProblem(null);
    setMode("starting");
    const next = recorder();
    try {
      await next.start();
    } catch {
      setMode("typing");
      setProblem("The microphone is not available: allow it in the browser, or type the question.");
      return;
    }
    active.current = next;
    setMode("recording");
    limit.current = setTimeout(() => void finish(true), MAX_SECONDS * 1000);
  };

  const recording = mode === "recording" && active.current;

  return (
    <div className="flex w-full flex-col gap-[9px]">
      {recording ? (
        <div
          role="group"
          aria-label="Recording your question"
          className="flex h-16 w-full items-center gap-4 rounded-card border border-accent bg-surface px-5 shadow-float"
        >
          <button
            type="button"
            aria-label="Cancel the recording"
            onClick={() => void finish(false)}
            className="inline-flex cursor-pointer rounded-full text-ink-muted hover:text-ink"
          >
            <Icon name="x" />
          </button>
          <span className="sr-only" role="status">
            Listening
          </span>
          <Waveform samples={recording.samples} />
          <button
            type="button"
            onClick={() => void finish(true)}
            className="inline-flex h-9 cursor-pointer items-center rounded-full bg-accent-fill px-4 text-small font-semibold text-on-accent"
          >
            Send
          </button>
        </div>
      ) : (
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
            onClick={() => void record()}
            disabled={!onVoice || mode === "starting"}
            aria-label="Ask by voice"
            className="inline-flex cursor-pointer rounded-full text-ink-muted hover:text-ink disabled:cursor-default disabled:hover:text-ink-muted"
          >
            <Icon name="mic" />
          </button>
        </form>
      )}
      {problem ? (
        <p role="alert" className="text-center text-caption text-danger-ink">
          {problem}
        </p>
      ) : (
        <p className="text-center text-caption text-ink-muted">{COMPOSER_PROMISE}</p>
      )}
    </div>
  );
}
