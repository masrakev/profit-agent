import { useId, useState } from "react";

import type { AgentStep } from "./model";
import { workingModel } from "./models";
import type { Names } from "./RichText";
import { stepFailed, stepText, visibleSteps } from "./steps";
import { AgentMark } from "@/ui/AgentMark";
import { cx } from "@/ui/cx";
import { Icon } from "@/ui/Icon";

interface WorkingProps {
  steps: AgentStep[];
  names: Names;
  /** Still working: the block is open and says so; once done it folds away. */
  live: boolean;
  /** The heading once done ("What I checked"). */
  title?: string;
  /** How long the work took, as the API says it ("41 s"), once done. */
  duration?: string | null;
}

/**
 * The agent's work, step by step, as it happens: what it read and checked, in plain words. While
 * it works the median of its mark moves and each step appears under a thin rule; once the answer
 * is there it folds into one line.
 */
export function Working({
  steps,
  names,
  live,
  title = "What I checked",
  duration = null,
}: WorkingProps) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const shown = visibleSteps(steps);
  const model = workingModel(steps);
  const expanded = live || open;

  return (
    <section aria-label={live ? "Working" : title} className="flex flex-col gap-3">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={listId}
        disabled={live}
        onClick={() => {
          setOpen((was) => !was);
        }}
        className="flex w-full cursor-pointer items-center justify-between gap-3 rounded-md text-small font-medium text-ink disabled:cursor-default"
      >
        <span className="flex items-center gap-2.5">
          {live ? (
            <AgentMark state="working" size="sm" />
          ) : (
            <Icon name="circle-check" size={16} className="text-ink-muted" />
          )}
          {live ? (model ? `Working with ${model}…` : "Working…") : title}
          {!live && duration && (
            <span className="font-mono text-label font-normal text-ink-muted">
              · took {duration}
            </span>
          )}
        </span>
        {!live && (
          <Icon
            name="chevron-up"
            className={cx(
              "text-ink-muted transition-transform duration-200",
              !open && "rotate-180",
            )}
          />
        )}
      </button>
      <ol
        id={listId}
        hidden={!expanded}
        aria-live={live ? "polite" : undefined}
        data-stagger
        className="ml-[7px] flex-col gap-2 border-l border-line pl-4 [&:not([hidden])]:flex"
      >
        {shown.length === 0 && live && (
          <li className="text-small text-ink-muted">Reading your question…</li>
        )}
        {shown.map((step, index) => (
          <li
            key={index}
            className={cx("text-small", stepFailed(step) ? "text-danger-ink" : "text-ink-muted")}
          >
            {stepText(step, names)}
            {stepFailed(step) && <span className="sr-only"> (it failed)</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}
