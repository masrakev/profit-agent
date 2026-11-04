import type { AgentStep } from "./model";

/** Meta's models as people name them, from the id the API reports for each call. */
const NAMES: [RegExp, (version: string) => string][] = [
  [/^muse-spark-open/, () => "Muse Spark Open"],
  [/^muse-spark-(\d+(?:\.\d+)*)/, (v) => `Muse Spark ${v}`],
  [/^muse-wonder-(\d+(?:\.\d+)*)/, (v) => `Muse Wonder ${v}`],
  [/^muse-voice-transcribe/, () => "Muse Voice"],
];

/** "muse-spark-1.3" (or "muse-spark-1.3-contributor") reads "Muse Spark 1.3"; null for none. */
export function modelName(id: string | null | undefined): string | null {
  if (!id) return null;
  const bare = id.replace(/^.*\//, "");
  for (const [pattern, name] of NAMES) {
    const found = pattern.exec(bare);
    if (found) return name(found[1] ?? "");
  }
  return bare;
}

/** The model the agent is working with: the last one that answered a call, by name. */
export function workingModel(steps: AgentStep[]): string | null {
  const last = steps.findLast((s) => s.kind === "model" && s.name);
  return modelName(last?.name);
}
