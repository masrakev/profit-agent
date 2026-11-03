import { cx } from "./cx";

/** Rows while their content loads: hairline-separated bars in the page's rhythm. */
export function Skeleton({ rows = 3, className }: { rows?: 2 | 3 | 4; className?: string }) {
  const widths = ["w-3/4", "w-1/2", "w-2/3", "w-2/5"].slice(0, rows);
  return (
    <div aria-busy="true" aria-label="Loading" className={cx("flex flex-col", className)}>
      {widths.map((width) => (
        <div key={width} className="flex flex-col gap-2 border-b border-line py-4">
          <span className={cx("h-3.5 animate-pulse rounded-bar bg-subtle", width)} />
          <span className="h-3 w-1/4 animate-pulse rounded-bar bg-subtle" />
        </div>
      ))}
    </div>
  );
}
