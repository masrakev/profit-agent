import { cx } from "./cx";

export type AgentState = "idle" | "working" | "waiting";

const SIZES = { sm: "size-4", md: "size-6", lg: "size-8" } as const;

/**
 * The agent's mark: a blue orb that rests when the agent is idle, breathes while it works, and
 * carries a small dot when something waits for the owner. Decorative: the words beside it (the
 * status line, a label) say the same.
 */
export function AgentMark({
  state = "idle",
  size = "md",
  className,
}: {
  state?: AgentState;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      data-state={state}
      className={cx("agent-mark", SIZES[size], className)}
    />
  );
}
