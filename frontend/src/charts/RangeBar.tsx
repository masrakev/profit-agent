import { rangeGeometry } from "./range";
import { estimateOf, quantileTexts, type Fact, type Precision } from "@/facts/facts";
import { useProof } from "@/facts/proofContext";
import { cx } from "@/ui/cx";

interface RangeBarProps {
  fact: Fact;
  /** Names the estimate for the proof sheet's title. */
  title?: string;
  /** False inside the proof sheet, where the bar is the proof itself. */
  interactive?: boolean;
  /** Short texts on screens; exact ones in the proof sheet. */
  precision?: Precision;
}

const pct = (fraction: number) => `${String(fraction * 100)}%`;

/**
 * An estimate as its range. On screens the range reads once ("low to high", the API's text), the
 * most likely value beside it, and the track below with the most likely value marked where it
 * falls. In the proof sheet each quantile is written under its place on the track. Nothing here
 * is computed for display: positions only place marks. An estimate without a usable range shows
 * its text alone.
 */
export function RangeBar({
  fact,
  title,
  interactive = true,
  precision = "display",
}: RangeBarProps) {
  const proof = useProof();
  const estimate = estimateOf(fact);
  const texts = quantileTexts(fact, precision);
  const geometry = estimate && rangeGeometry(estimate.p10, estimate.p50, estimate.p90);
  if (!estimate || !texts || !geometry) {
    return <p className="text-label text-ink-muted">{fact.display}</p>;
  }

  const track = (
    <span aria-hidden="true" className="relative block h-1.5 w-full rounded-full bg-accent-soft">
      <span className="absolute inset-y-0 right-[3px] left-[3px] block">
        <Dot at={geometry.low} part="low" />
        <span
          data-part="likely"
          className="absolute top-1/2 block h-3 w-[3px] -translate-1/2 rounded-bar bg-accent-mark"
          style={{ left: pct(geometry.mark) }}
        />
        <Dot at={geometry.high} part="high" />
      </span>
    </span>
  );

  if (!interactive) {
    return (
      <div className="flex w-full flex-col gap-2 text-left">
        <span className="flex w-full items-start justify-between text-label whitespace-nowrap tabular-nums">
          <span className="text-ink-muted">{texts.p10}</span>
          <span className="font-semibold text-accent-ink">{texts.p50}</span>
          <span className="text-ink-muted">{texts.p90}</span>
        </span>
        {track}
        <span className="flex w-full items-start justify-between text-label whitespace-nowrap text-ink-muted">
          <span>Low</span>
          <span>Most likely</span>
          <span>High</span>
        </span>
      </div>
    );
  }

  return (
    <button
      type="button"
      aria-haspopup="dialog"
      aria-label={`${fact.display}, most likely ${texts.p50}, see the proof`}
      data-fact={fact.fact_id}
      className={cx("group flex w-full cursor-pointer flex-col gap-2.5 rounded-md text-left")}
      onClick={() => {
        proof.open(fact, title);
      }}
    >
      <span className="flex w-full flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="text-body font-medium text-ink underline decoration-line decoration-1 underline-offset-[5px] group-hover:decoration-ink-muted">
          {fact.display}
        </span>
        <span className="text-label text-ink-muted">
          <span>Most likely</span> <span className="font-medium text-accent-ink">{texts.p50}</span>
        </span>
      </span>
      {track}
    </button>
  );
}

function Dot({ at, part }: { at: number; part: string }) {
  return (
    <span
      data-part={part}
      className="absolute top-1/2 block size-[5px] -translate-1/2 rounded-full bg-accent-mark"
      style={{ left: pct(at) }}
    />
  );
}
