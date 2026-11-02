/** Identifiers from the API ("net_profit", "order_lines") as words: "Net profit", "Order lines". */
export function humanize(identifier: string): string {
  const words = identifier.replace(/[_.:-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "1 row", "12 rows": a count the API gave, with its noun. */
export function counted(count: number, singular: string, plural = `${singular}s`): string {
  return `${String(count)} ${count === 1 ? singular : plural}`;
}
