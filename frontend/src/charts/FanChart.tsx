import { useState } from "react";

import { estimateOf, type Fact } from "@/facts/facts";
import { cx } from "@/ui/cx";

export interface FanWeek {
  /** Days since the goal started: places the week along the axis. */
  day: number;
  /** The week's date, already in words. */
  label: string;
  /** The plan's cumulative net profit to that day, as an estimate (P10, P50, P90). */
  milestone: Fact;
  /** What was measured by then, when the week has passed. */
  actual?: Fact;
}

const WIDTH = 640;
const HEIGHT = 220;
const PAD = { top: 12, right: 12, bottom: 12, left: 12 };

/** A value the API wrote, as a number for plotting (never shown). */
function plotted(fact: Fact | undefined): number | null {
  if (fact?.status !== "defined" || fact.value == null) return null;
  const value = Number(fact.value);
  return Number.isFinite(value) ? value : null;
}

/**
 * The plan week by week: the band where the cumulative net profit should be (P10 to P90), its most
 * likely path, what was measured so far, and the target. Plotting only: every text is a fact's own,
 * in the tooltip and in the list beside the chart; the axis has no numbers of its own.
 */
export function FanChart({
  weeks,
  target,
  label,
}: {
  weeks: FanWeek[];
  target?: Fact;
  label: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const points = weeks.flatMap((w) => {
    const e = estimateOf(w.milestone);
    if (!e) return [];
    const [p10, p50, p90] = [Number(e.p10), Number(e.p50), Number(e.p90)];
    return [p10, p50, p90].every(Number.isFinite) ? [{ week: w, p10, p50, p90 }] : [];
  });
  if (points.length < 2) return null;

  const goal = plotted(target);
  const actuals = points.map((p) => plotted(p.week.actual));
  const values = [
    ...points.flatMap((p) => [p.p10, p.p90]),
    ...actuals.flatMap((a) => (a === null ? [] : [a])),
    ...(goal === null ? [] : [goal]),
    0,
  ];
  const [low, high] = [Math.min(...values), Math.max(...values)];
  const first = 0;
  const last = Math.max(...points.map((p) => p.week.day));
  const x = (day: number) =>
    PAD.left + ((day - first) / (last - first || 1)) * (WIDTH - PAD.left - PAD.right);
  const y = (value: number) =>
    HEIGHT - PAD.bottom - ((value - low) / (high - low || 1)) * (HEIGHT - PAD.top - PAD.bottom);

  const at = (day: number) => `${String((x(day) / WIDTH) * 100)}%`;
  const xy = (day: number, value: number) => `${String(x(day))},${String(y(value))}`;
  const start = xy(0, 0); // the goal counts from zero on its first day
  const band = [
    start,
    ...points.map((p) => xy(p.week.day, p.p90)),
    ...points.toReversed().map((p) => xy(p.week.day, p.p10)),
  ].join(" ");
  const likely = [start, ...points.map((p) => xy(p.week.day, p.p50))].join(" ");
  const shown = hover === null ? null : points[hover];

  return (
    <figure className="flex flex-col gap-3">
      <div className="relative">
        <svg
          viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
          role="img"
          aria-label={label}
          className="block h-auto w-full overflow-visible"
          onMouseLeave={() => {
            setHover(null);
          }}
        >
          <line
            x1={PAD.left}
            x2={WIDTH - PAD.right}
            y1={y(0)}
            y2={y(0)}
            className="stroke-line"
            strokeWidth={1}
          />
          <polygon points={band} data-part="band" className="fill-accent-mark/15" />
          <polyline
            points={likely}
            data-part="likely"
            fill="none"
            className="stroke-accent-mark"
            strokeWidth={2}
            strokeLinejoin="round"
          />
          {goal !== null && (
            <line
              data-part="target"
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={y(goal)}
              y2={y(goal)}
              className="stroke-ink-muted"
              strokeWidth={1}
              strokeDasharray="4 4"
            />
          )}
          {shown && (
            <line
              x1={x(shown.week.day)}
              x2={x(shown.week.day)}
              y1={PAD.top}
              y2={HEIGHT - PAD.bottom}
              className="stroke-line"
              strokeWidth={1}
            />
          )}
          {points.map((p, i) => {
            const a = actuals[i];
            return a === null || a === undefined ? null : (
              <circle
                key={p.week.day}
                data-part="actual"
                cx={x(p.week.day)}
                cy={y(a)}
                r={5}
                className="fill-ink stroke-surface"
                strokeWidth={2}
              />
            );
          })}
          {points.map((p, i) => {
            const step = (WIDTH - PAD.left - PAD.right) / Math.max(points.length, 1);
            return (
              <rect
                key={`hit-${String(p.week.day)}`}
                x={x(p.week.day) - step / 2}
                y={0}
                width={step}
                height={HEIGHT}
                fill="transparent"
                onMouseEnter={() => {
                  setHover(i);
                }}
              />
            );
          })}
        </svg>
        {shown && (
          <div
            role="status"
            className={cx(
              "pointer-events-none absolute top-0 z-10 flex flex-col gap-0.5 rounded-[8px] border border-line bg-surface px-3 py-2 text-label whitespace-nowrap text-ink shadow-float",
              // Kept inside the chart near its edges.
              x(shown.week.day) < WIDTH * 0.2
                ? "translate-x-0"
                : x(shown.week.day) > WIDTH * 0.8
                  ? "-translate-x-full"
                  : "-translate-x-1/2",
            )}
            style={{ left: at(shown.week.day) }}
          >
            <span className="font-semibold">{shown.week.label}</span>
            <span className="text-ink-muted">Plan: {shown.week.milestone.display}</span>
            {shown.week.actual && <span>Actual: {shown.week.actual.display}</span>}
          </div>
        )}
      </div>
      <div aria-hidden="true" className="relative h-4 text-caption text-ink-muted">
        {[points[0], points.at(-1)].map((p, i) =>
          p ? (
            <span
              key={p.week.day}
              className={cx(
                "absolute top-0 whitespace-nowrap",
                i === 0 ? "-translate-x-1/2" : "-translate-x-full",
              )}
              style={{ left: at(p.week.day) }}
            >
              {p.week.label}
            </span>
          ) : null,
        )}
      </div>
      <figcaption className="flex flex-wrap items-center gap-x-5 gap-y-2 text-label text-ink-muted">
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="h-2.5 w-5 rounded-[2px] bg-accent-mark/15" />
          Likely range with the plan
        </span>
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="h-0.5 w-5 rounded-full bg-accent-mark" />
          Most likely
        </span>
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="size-2.5 rounded-full bg-ink" />
          Actual
        </span>
        {target && (
          <span className="inline-flex items-center gap-2">
            <span aria-hidden="true" className="w-5 border-t border-dashed border-ink-muted" />
            Target, {target.display}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
