import type { ReactNode } from "react";

import { cx } from "./cx";

export type Tone = "good" | "warning" | "critical" | "info" | "neutral";

const DOTS: Record<Tone, string> = {
  good: "bg-good",
  warning: "bg-warning",
  critical: "bg-danger",
  info: "bg-accent-mark",
  neutral: "bg-ink-muted",
};

/**
 * A status in words with a small coloured dot, no background: the words carry the meaning, the
 * dot only echoes it.
 */
export function StatusPill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-label font-medium whitespace-nowrap text-ink-muted">
      <span
        aria-hidden="true"
        data-tone={tone}
        className={cx("size-1.5 rounded-full", DOTS[tone])}
      />
      {children}
    </span>
  );
}
