import { AgentMark } from "./AgentMark";
import { BRAND } from "@/brand";

/** The brand: the agent's mark. With `named`, the product name follows. */
export function BrandMark({ named = false }: { named?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <AgentMark size="md" />
      {named ? (
        <span className="text-brand font-semibold tracking-[-0.01em] text-ink">{BRAND.name}</span>
      ) : (
        <span className="sr-only">{BRAND.name}</span>
      )}
    </span>
  );
}
