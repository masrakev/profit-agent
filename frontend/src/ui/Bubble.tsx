import type { ReactNode } from "react";

import { cx } from "./cx";

/**
 * A message in the conversation: the owner's on the right on a quiet tint, the agent's on the left.
 * Children are React text, so merchant-provided words are escaped, never parsed as HTML.
 */
export function Bubble({ from, children }: { from: "owner" | "agent"; children: ReactNode }) {
  return (
    <div className={cx("flex w-full", from === "owner" ? "justify-end" : "justify-start")}>
      <div
        data-from={from}
        className={cx(
          "max-w-[min(560px,85%)] rounded-bubble px-4 py-2.5 text-body text-ink",
          from === "owner" ? "bg-bubble-owner" : "bg-subtle",
        )}
      >
        {children}
      </div>
    </div>
  );
}
