import { useId, useState } from "react";

import { RangeBar } from "@/charts/RangeBar";
import { estimateOf, type Fact } from "@/facts/facts";
import { FactValue } from "@/facts/FactValue";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";
import { Icon } from "@/ui/Icon";
import type { IconName } from "@/ui/icons";

export interface PermissionOption {
  id: string;
  /** What the option does, in words ("Pause until restock"). */
  label: string;
  /** Its expected impact against doing nothing, a fact from the API (an estimate is a range). */
  impact: Fact | null;
  recommended?: boolean;
}

export interface PermissionCardProps {
  /** The question asked of the owner ("Pause ‘Trail Jacket — Prospecting’ until restock?"). */
  question: string;
  icon?: IconName;
  /** What the impacts are measured against ("Compared with doing nothing over 14 days"). */
  comparedWith: string;
  options: PermissionOption[];
  /** The do-nothing option, last and without a range. */
  baseline?: { label: string; impact: Fact | null };
  /** The safety checks, in words. */
  safety: string;
  onApprove: () => void;
  onDecline: () => void;
  /** While the owner's answer is being sent: both buttons wait. */
  pending?: boolean;
  /** A safety check would stop it: it cannot be approved. */
  blocked?: boolean;
}

/**
 * The agent asks before it acts: the question, every option with its range (P10 to P90, P50 marked),
 * the safety checks, and Approve or Not now. Nothing changes until the owner answers.
 */
export function PermissionCard({
  question,
  icon = "pause",
  comparedWith,
  options,
  baseline,
  safety,
  onApprove,
  onDecline,
  pending = false,
  blocked = false,
}: PermissionCardProps) {
  const [expanded, setExpanded] = useState(true);
  const summaryId = useId();
  const questionId = useId();
  const sealed = options.find((option) => option.recommended)?.impact ?? options[0]?.impact;

  return (
    <article
      aria-labelledby={questionId}
      className="flex w-full flex-col gap-5 rounded-card border border-line bg-surface p-6 shadow-float"
    >
      <header className="flex items-start gap-3">
        <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-box bg-accent-soft text-accent-ink">
          <Icon name={icon} />
        </span>
        <h3 id={questionId} className="flex-1 text-card font-semibold text-ink">
          {question}
        </h3>
        {sealed && <VerifiedSeal fact={sealed} />}
      </header>

      <section className="flex flex-col gap-4 rounded-box bg-subtle p-4">
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={summaryId}
          onClick={() => {
            setExpanded((shown) => !shown);
          }}
          className="flex w-full cursor-pointer items-start justify-between text-body font-semibold text-ink"
        >
          Summary
          <Icon
            name="chevron-up"
            className={cx("text-ink-muted transition-transform", !expanded && "rotate-180")}
          />
        </button>
        <div id={summaryId} hidden={!expanded} className="flex-col gap-4 [&:not([hidden])]:flex">
          <p className="text-label leading-[1.45] text-ink-muted">{comparedWith}</p>
          {options.map((option, index) => (
            <div key={option.id} className="flex flex-col gap-4">
              {index > 0 && <hr className="border-line" />}
              <div className="flex flex-col gap-2.5">
                <p className={cx("text-small text-ink", option.recommended && "font-semibold")}>
                  {option.label}
                  {option.impact && (
                    <>
                      {" "}
                      <FactValue fact={option.impact} title={option.label} />
                    </>
                  )}
                  {option.recommended && " (recommended)"}
                </p>
                {option.impact && estimateOf(option.impact) && (
                  <RangeBar fact={option.impact} title={option.label} />
                )}
              </div>
            </div>
          ))}
          {baseline && (
            <>
              <hr className="border-line" />
              <p className="flex items-start justify-between gap-4 text-small text-ink">
                <span>{baseline.label}</span>
                {baseline.impact && <FactValue fact={baseline.impact} title={baseline.label} />}
              </p>
            </>
          )}
        </div>
      </section>

      <p className={cx("text-small", blocked ? "text-danger-ink" : "text-ink-muted")}>{safety}</p>

      <div className="flex flex-wrap gap-2.5">
        <Button onClick={onApprove} disabled={pending || blocked} aria-busy={pending}>
          Approve
        </Button>
        <Button variant="secondary" onClick={onDecline} disabled={pending}>
          Not now
        </Button>
      </div>
    </article>
  );
}
