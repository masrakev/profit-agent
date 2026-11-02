import { useId, useState } from "react";

import type { AgentStep } from "./model";
import type { Names } from "./RichText";
import { stepFailed, stepText, visibleSteps } from "./steps";
import { cx } from "@/ui/cx";
import { Icon } from "@/ui/Icon";

interface WorkingProps {
  steps: AgentStep[];
  names: Names;
  /** Still working: the block is open and says so; once done it folds away. */
  live: boolean;
  /** The heading once done ("What I checked"). */
  title?: string;
}

/**
 * The agent's work, step by step, as it happens: what it read and checked, in plain words. While
 * it works the block is open and live; once the answer is there it folds into one line.
 */
export function Working({ steps, names, live, title = "What I checked" }: WorkingProps) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const shown = visibleSteps(steps);
  const expanded = live || open;

  return (
    <section
      aria-label={live ? "Working" : title}
      className="flex flex-col gap-2 rounded-box border border-line bg-surface px-4 py-3"
    >
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={listId}
        disabled={live}
        onClick={() => {
          setOpen((was) => !was);
        }}
        className="flex w-full cursor-pointer items-center justify-between gap-3 text-small font-semibold text-ink disabled:cursor-default"
      >
        <span className="flex items-center gap-2">
          {live ? (
            <span
              aria-hidden="true"
              className="size-2 animate-pulse rounded-full bg-accent"
              data-part="live"
            />
          ) : (
            <Icon name="circle-check" size={16} className="text-accent-ink" />
          )}
          {live ? "Working…" : title}
        </span>
        {!live && (
          <Icon
            name="chevron-up"
            className={cx("text-ink-muted transition-transform", !open && "rotate-180")}
          />
        )}
      </button>
      <ol
        id={listId}
        hidden={!expanded}
        aria-live={live ? "polite" : undefined}
        className="flex-col gap-1.5 [&:not([hidden])]:flex"
      >
        {shown.length === 0 && live && (
          <li className="text-small text-ink-muted">Reading your question…</li>
        )}
        {shown.map((step, index) => (
          <li
            key={index}
            className={cx(
              "flex items-start gap-2 text-small",
              stepFailed(step) ? "text-danger-ink" : "text-ink-muted",
            )}
          >
            <span aria-hidden="true" className="mt-[7px] size-1 shrink-0 rounded-full bg-current" />
            {stepText(step, names)}
            {stepFailed(step) && <span className="sr-only"> (it failed)</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}
