import { cx } from "./cx";

export type AgentState = "idle" | "working" | "waiting";

const SIZES = { sm: "size-4", md: "size-5", lg: "size-8" } as const;

/**
 * The agent's mark: a range with its median, the product's own sign (every estimate it shows is
 * a range, the median marked). It rests when the agent is idle; while it works the median moves
 * along the range; a small dot says something waits for the owner. Decorative: the words beside
 * it (the status line, a label) say the same.
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
    >
      <svg viewBox="0 0 20 20" focusable="false">
        <path className="range" d="M3 7v6M17 7v6M3 10h14" />
        <path className="median" d="M11 4.5v11" />
      </svg>
    </span>
  );
}
