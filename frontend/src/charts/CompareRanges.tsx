import { rangeGeometry, sharedDomain } from "./range";
import { FactValue } from "@/facts/FactValue";
import { estimateOf, type Fact } from "@/facts/facts";

export interface Compared {
  label: string;
  fact: Fact;
}

const pct = (fraction: number) => `${String(fraction * 100)}%`;

/**
 * Estimates on one axis, so they can be compared by eye: what was predicted and what was
 * measured, each as its P10–P90 band with its most likely value marked. Plotting only: the texts
 * are the facts' own, each opening its proof; nothing here says whether one is inside the other.
 */
export function CompareRanges({ rows }: { rows: Compared[] }) {
  const estimates = rows.map((r) => estimateOf(r.fact));
  const domain = sharedDomain(estimates.flatMap((e) => (e ? [e] : [])));
  return (
    // One grid for every row, so the ranges share their axis on screen too.
    <ul className="grid grid-cols-[6rem_1fr_auto] items-center gap-x-4 gap-y-3">
      {rows.map((row, index) => {
        const e = estimates[index];
        const geometry = e && domain && rangeGeometry(e.p10, e.p50, e.p90, domain);
        return (
          <li
            key={row.label}
            className="col-span-full grid grid-cols-subgrid items-center text-small"
          >
            <span className="text-ink-muted">{row.label}</span>
            <span aria-hidden="true" className="relative block h-2 rounded-full bg-subtle">
              {geometry && (
                <>
                  <span
                    data-part="range"
                    className="absolute inset-y-0 block rounded-full bg-accent-mark/35"
                    style={{
                      left: pct(geometry.low),
                      width: pct(Math.max(geometry.high - geometry.low, 0.01)),
                    }}
                  />
                  <span
                    data-part="likely"
                    className="absolute top-1/2 block h-3.5 w-1 -translate-1/2 rounded-[2px] bg-accent-mark"
                    style={{ left: pct(geometry.mark) }}
                  />
                </>
              )}
            </span>
            <FactValue fact={row.fact} title={row.label} className="justify-self-end text-ink" />
          </li>
        );
      })}
    </ul>
  );
}
