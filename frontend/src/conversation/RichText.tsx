import type { ReactNode } from "react";

import { useFactDetail, type Fact } from "@/facts/facts";
import { FactValue } from "@/facts/FactValue";
import { useStore } from "@/stores/store";

export type Facts = Record<string, Fact>;
export type Names = Record<string, string>;

// `{{F<id>}}` cites a fact; `{{E:store}}`, `{{E:product:<uuid>}}`, `{{E:campaign:<uuid>}}` an entity.
const REFERENCE = /\{\{(?:F(\d+)|E:(store|(?:product|campaign):[0-9a-f-]{36}))\}\}/g;

const FALLBACK: Record<string, string> = {
  store: "your store",
  product: "a product",
  campaign: "a campaign",
};

/**
 * Text written with references, as the API sends it (answers, briefs, reports): each fact is
 * shown by its short text as a button that opens its proof, each entity by its name. Names are
 * merchant data: React renders them as text, never as markup.
 */
export function RichText({ text, facts, names }: { text: string; facts: Facts; names: Names }) {
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(REFERENCE)) {
    const at = match.index;
    if (at > last) out.push(text.slice(last, at));
    const [, factId, entity] = match;
    if (factId) {
      const fact = facts[factId];
      out.push(
        fact ? (
          <FactValue key={at} fact={fact} />
        ) : (
          <FetchedFact key={at} factId={Number(factId)} />
        ),
      );
    } else if (entity) {
      const name = names[entity] ?? FALLBACK[entity.split(":")[0] ?? ""] ?? "it";
      out.push(
        <span key={at} className="font-medium" data-entity={entity}>
          {name}
        </span>,
      );
    }
    last = at + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

/** A cited fact the response did not carry: read by its id, then shown like the others. */
function FetchedFact({ factId }: { factId: number }) {
  const { storeId } = useStore();
  const detail = useFactDetail(storeId, factId);
  if (detail.data) return <FactValue fact={detail.data.fact} />;
  return (
    <span aria-busy={detail.isPending} className="text-ink-muted">
      {detail.isError ? "(unavailable)" : "…"}
    </span>
  );
}
