import type { ReactNode } from "react";

import { cx } from "./cx";

export type Tone = "good" | "warning" | "critical" | "info" | "neutral";

const DOTS: Record<Tone, string> = {
  good: "bg-good",
  warning: "bg-warning",
  critical: "bg-danger",
  info: "bg-accent",
  neutral: "bg-ink-muted",
};

/** A status in words with a coloured dot; the words carry the meaning, the dot only echoes it. */
export function StatusPill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-subtle px-2.5 py-[5px] text-label font-medium text-ink">
      <span
        aria-hidden="true"
        data-tone={tone}
        className={cx("size-[5px] rounded-full", DOTS[tone])}
      />
      {children}
    </span>
  );
}
