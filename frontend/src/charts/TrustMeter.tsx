/**
 * Earned autonomy's progress as ticks: one per confirmation the threshold asks for, the ones
 * already earned filled. Plotting only: the counts are the API's, and the sentence beside it
 * (also the API's) says them in words.
 */
export function TrustMeter({
  confirmations,
  threshold,
}: {
  confirmations: number;
  threshold: number;
}) {
  if (threshold <= 0) return null;
  const ticks = Array.from({ length: threshold }, (_, index) => index < confirmations);
  return (
    <span aria-hidden="true" className="flex gap-[3px]" data-part="trust-meter">
      {ticks.map((earned, index) => (
        <span
          key={index}
          data-earned={earned}
          className={earned ? "h-3 w-1 rounded-bar bg-accent-mark" : "h-3 w-1 rounded-bar bg-line"}
        />
      ))}
    </span>
  );
}
