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
  level = 2,
}: {
  title: string;
  aside?: ReactNode;
  /** Its heading's level: 2 on a page, 3 inside a titled part of one. */
  level?: 2 | 3;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  const Heading = level === 3 ? "h3" : "h2";
  return (
    <section aria-labelledby={id} className={cx("flex flex-col", className)}>
      <div className="flex items-baseline justify-between gap-3 border-b border-line pb-2.5">
        <Heading id={id} className="text-small font-medium text-ink-muted">
          {title}
        </Heading>
        {aside}
      </div>
      {children}
    </section>
  );
}
