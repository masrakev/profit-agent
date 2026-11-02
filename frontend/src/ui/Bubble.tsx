import type { ReactNode } from "react";

import { cx } from "./cx";

/**
 * A message in the conversation: the owner's on the right in blue, the agent's on the left in grey.
 * Children are React text, so merchant-provided words are escaped, never parsed as HTML.
 */
export function Bubble({ from, children }: { from: "owner" | "agent"; children: ReactNode }) {
  return (
    <div className={cx("flex w-full", from === "owner" ? "justify-end" : "justify-start")}>
      <div
        data-from={from}
        className={cx(
          "max-w-[620px] rounded-bubble px-5 py-3.5 text-body text-ink",
          from === "owner" ? "bg-bubble-owner" : "bg-subtle",
        )}
      >
        {children}
      </div>
    </div>
  );
}
