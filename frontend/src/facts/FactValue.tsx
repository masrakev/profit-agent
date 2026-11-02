import type { Fact } from "./facts";
import { useProof } from "./proofContext";
import { cx } from "@/ui/cx";

interface FactValueProps {
  fact: Fact;
  /** Names the number in its context, for the proof sheet's title. */
  title?: string;
  className?: string;
}

/** A number on screen: the API's formatted text, and a button that opens its proof. */
export function FactValue({ fact, title, className }: FactValueProps) {
  const proof = useProof();
  return (
    <button
      type="button"
      aria-haspopup="dialog"
      data-fact={fact.fact_id}
      onClick={() => {
        proof.open(fact, title);
      }}
      className={cx(
        // As in Figma, a dotted underline says the number opens its proof.
        "inline cursor-pointer rounded-[4px] underline decoration-ink-muted decoration-dotted",
        "decoration-1 underline-offset-[5px] hover:text-accent-ink hover:decoration-accent-ink",
        className,
      )}
    >
      {fact.formatted}
      <span className="sr-only">, see the proof</span>
    </button>
  );
}
