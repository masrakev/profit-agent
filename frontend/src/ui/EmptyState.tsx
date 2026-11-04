import type { ReactNode } from "react";

/** Nothing here yet, said as an invitation: what will appear, and what to do now. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 py-10">
      <p className="text-body font-medium text-ink">{title}</p>
      {children && <div className="max-w-[52ch] text-small text-ink-muted">{children}</div>}
    </div>
  );
}
