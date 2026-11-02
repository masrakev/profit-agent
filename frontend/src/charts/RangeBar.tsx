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
 * An estimate as its range: the low (P10), most likely (P50) and high (P90) values as the API
 * wrote them, and the track with the most likely value marked where it falls. Nothing here is
 * computed for display: positions only place marks. An estimate without a usable range shows its
 * text alone.
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

  const content = (
    <>
      <span className="flex w-full items-start justify-between text-label whitespace-nowrap">
        <span className="text-ink-muted">{texts.p10}</span>
        <span className="font-semibold text-accent-ink">{texts.p50}</span>
        <span className="text-ink-muted">{texts.p90}</span>
      </span>
      <span
        aria-hidden="true"
        className="relative block h-2 w-full overflow-hidden rounded-full bg-accent-soft"
      >
        <span className="absolute inset-y-0 right-[6.5px] left-[6.5px] block">
          <Dot at={geometry.low} part="low" />
          <span
            data-part="likely"
            className="absolute top-1/2 block h-3.5 w-1 -translate-1/2 rounded-[2px] bg-accent"
            style={{ left: pct(geometry.mark) }}
          />
          <Dot at={geometry.high} part="high" />
        </span>
      </span>
      <span className="flex w-full items-start justify-between text-caption whitespace-nowrap text-ink-muted">
        <span>Low</span>
        <span>Most likely</span>
        <span>High</span>
      </span>
    </>
  );

  const layout = "flex w-full flex-col gap-2 text-left";
  if (!interactive) return <div className={layout}>{content}</div>;
  return (
    <button
      type="button"
      aria-haspopup="dialog"
      aria-label={`${fact.display}, most likely ${texts.p50}, see the proof`}
      data-fact={fact.fact_id}
      className={cx(layout, "cursor-pointer rounded-[6px]")}
      onClick={() => {
        proof.open(fact, title);
      }}
    >
      {content}
    </button>
  );
}

function Dot({ at, part }: { at: number; part: string }) {
  return (
    <span
      data-part={part}
      className="absolute top-1/2 block size-[5px] -translate-1/2 rounded-full bg-accent"
      style={{ left: pct(at) }}
    />
  );
}
