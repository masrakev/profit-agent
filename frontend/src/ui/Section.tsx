import { useId, type ReactNode } from "react";

import { cx } from "./cx";

/**
 * A section of a page: its title as a quiet label over a hairline, an optional note or action on
 * the right, then its content. Sections, not cards, carry the hierarchy.
 */
export function Section({
  title,
  aside,
  children,
  className,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={cx("flex flex-col", className)}>
      <div className="flex items-baseline justify-between gap-3 border-b border-line pb-2.5">
        <h2 id={id} className="text-small font-medium text-ink-muted">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}
