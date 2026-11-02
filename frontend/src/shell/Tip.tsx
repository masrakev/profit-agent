import type { ReactNode } from "react";

/** A label shown beside a collapsed row on hover or keyboard focus (the row names itself). */
export function Tip({ show, children }: { show: boolean; children: ReactNode }) {
  if (!show) return null;
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute top-1/2 left-full z-50 ml-2 -translate-y-1/2 rounded-[8px] bg-ink px-2 py-1 text-label font-medium whitespace-nowrap text-canvas opacity-0 transition-opacity group-focus-within/tip:opacity-100 group-hover/tip:opacity-100"
    >
      {children}
    </span>
  );
}
