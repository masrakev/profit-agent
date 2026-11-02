import { FactValue } from "@/facts/FactValue";
import type { Fact } from "@/facts/facts";
import { cx } from "@/ui/cx";

export interface Driver {
  driver: string;
  fact: Fact;
  /** False: the effect is inside the driver's usual week-to-week variation. */
  significant?: boolean | null;
}

const pct = (fraction: number) => `${String(fraction * 100)}%`;

/**
 * What moved net profit: each driver's effect as a bar from the centre, right when it added
 * profit, left when it took some away, as long as the largest effect allows. Plotting only: the
 * lengths place bars, the numbers shown are the facts' own texts, each opening its proof.
 */
export function DriverBars({ drivers }: { drivers: Driver[] }) {
  const values = drivers.map((d) => Number(d.fact.value));
  const largest = Math.max(0, ...values.filter(Number.isFinite).map(Math.abs));
  return (
    <ul className="flex flex-col gap-3">
      {drivers.map((d, index) => {
        const value = values[index] ?? Number.NaN;
        const length = Number.isFinite(value) && largest > 0 ? Math.abs(value) / largest / 2 : 0;
        const gained = value >= 0;
        return (
          <li
            key={d.driver}
            className="grid grid-cols-[minmax(0,14rem)_1fr_auto] items-center gap-4 text-small"
          >
            <span className="flex flex-col">
              <span className="text-ink">{d.fact.name}</span>
              {d.significant === false && (
                <span className="text-caption text-ink-muted">Within its usual variation</span>
              )}
            </span>
            <span aria-hidden="true" className="relative block h-2 rounded-full bg-subtle">
              <span className="absolute inset-y-[-3px] left-1/2 w-px bg-line" />
              {length > 0 && (
                <span
                  data-part={gained ? "gain" : "loss"}
                  className={cx(
                    "absolute inset-y-0 block rounded-full",
                    gained ? "bg-good" : "bg-danger",
                  )}
                  style={
                    gained
                      ? { left: "50%", width: pct(length) }
                      : { right: "50%", width: pct(length) }
                  }
                />
              )}
            </span>
            <FactValue fact={d.fact} title={d.fact.name} className="text-ink" />
          </li>
        );
      })}
    </ul>
  );
}
