import { BRAND } from "@/brand";

const SIGNALS = ["h-[9px]", "h-4", "h-[11px]"];

/** The brand mark: three signal bars on the accent square. With `named`, the product name follows. */
export function BrandMark({ named = false }: { named?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span
        aria-hidden="true"
        className="inline-flex size-[30px] items-center justify-center gap-[3px] rounded-mark bg-accent-mark"
      >
        {SIGNALS.map((height) => (
          <span key={height} className={`w-1 rounded-bar bg-on-accent ${height}`} />
        ))}
      </span>
      {named ? (
        <span className="text-brand font-semibold text-ink">{BRAND.name}</span>
      ) : (
        <span className="sr-only">{BRAND.name}</span>
      )}
    </span>
  );
}
