import type { Facts, Names } from "./RichText";

const REFERENCE = /\{\{(?:F(\d+)|E:(store|(?:product|campaign):[0-9a-f-]{36}))\}\}/g;

/** Text written with references, in plain words: each fact by its short text, each entity by name. */
export function plainText(text: string, facts: Facts, names: Names): string {
  return text.replace(REFERENCE, (_, factId: string | undefined, entity: string | undefined) => {
    if (factId) return facts[factId]?.display ?? "";
    return (entity && names[entity]) ?? "it";
  });
}
