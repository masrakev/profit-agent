import { cx } from "@/ui/cx";

const STEPS = [
  { key: "unlikely", label: "Unlikely" },
  { key: "stretch", label: "A stretch" },
  { key: "possible", label: "Possible" },
  { key: "likely", label: "Likely" },
] as const;

/**
 * Whether a goal is within reach as a band of four steps, the verdict (or, beyond 90 days, the
 * interval of verdicts it lies in) lit. The words under each step say the same as the light.
 */
export function VerdictBand({ band }: { band: string[] }) {
  const index = (key: string | undefined) => STEPS.findIndex((s) => s.key === key);
  const [low, high] = [index(band[0]), index(band.at(-1))];
  return (
    <div aria-hidden="true" className="grid grid-cols-4 gap-1" data-part="verdict-band">
      {STEPS.map((step, i) => {
        const lit = low >= 0 && high >= 0 && i >= Math.min(low, high) && i <= Math.max(low, high);
        return (
          <span key={step.key} data-lit={lit} className="flex flex-col gap-1.5">
            <span className={cx("h-1.5 rounded-bar", lit ? "bg-accent-mark" : "bg-line")} />
            <span className={cx("text-label", lit ? "font-medium text-ink" : "text-ink-muted")}>
              {step.label}
            </span>
          </span>
        );
      })}
    </div>
  );
}
