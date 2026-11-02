/**
 * The agent's steps in plain words, for the "Working" block. A tool step names what it looked at
 * (a product or a campaign, by name when the conversation knows it); a model step is the agent
 * reasoning over what it read. No number is shown: tokens and counts are not the owner's.
 */

import type { AgentStep } from "./model";
import type { Names } from "./RichText";
import { humanize } from "@/format/words";

const TOOLS: Record<string, string> = {
  get_incident: "Read the problem and its symptoms",
  list_incidents: "Listed the open problems",
  get_profit_bridge: "Split the change in profit between its drivers",
  get_facts: "Read {metric} for {entity}",
  get_series_summary: "Followed {metric} day by day for {entity}",
  compare_entities: "Compared {metric} across {entity}",
  compute: "Worked out a number from the facts",
  list_products: "Listed the products",
  get_campaign_context: "Looked at {entity}",
  get_inventory_context: "Checked the stock of {entity}",
  get_data_quality: "Checked the data is complete and up to date",
  check_reconciliation: "Compared the ad platform's sales with your orders for {entity}",
  run_sensitivity: "Checked the cause holds over other time windows",
  get_method: "Read how a number is calculated",
};

const KINDS: Record<string, string> = {
  started: "Started",
  model: "Weighed the evidence",
  regeneration: "Rewrote the answer to cite only verified numbers",
  answer: "Wrote the answer",
  cache_hit: "Reused a recent check of the same data",
  stopped: "Stopped",
  done: "Done",
  failed: "Could not finish",
};

function args(step: AgentStep): Record<string, unknown> {
  const raw = step.detail["arguments"];
  if (typeof raw !== "string") return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** What the step looked at: "Trail Jacket", "‘Trail Jacket — Prospecting’", or a fallback. */
function entity(given: Record<string, unknown>, names: Names): string {
  const scope = given["scope"] as { kind?: unknown; id?: unknown } | undefined;
  const pairs: [string, unknown][] = [
    ["product", given["product_id"]],
    ["campaign", given["campaign_id"]],
    [typeof scope?.kind === "string" ? scope.kind : "", scope?.id],
  ];
  for (const [kind, id] of pairs) {
    if (typeof id !== "string" || !kind) continue;
    const name = names[`${kind}:${id}`];
    if (name) return kind === "campaign" ? `‘${name}’` : name;
    return kind === "campaign" ? "a campaign" : "a product";
  }
  return scope?.kind === "store" ? "the store" : "your store";
}

export function stepText(step: AgentStep, names: Names): string {
  if (step.kind === "tool" && step.name) {
    const given = args(step);
    const template = TOOLS[step.name] ?? humanize(step.name);
    const metric =
      typeof given["metric"] === "string" ? humanize(given["metric"]).toLowerCase() : "";
    return template
      .replace("{entity}", entity(given, names))
      .replace("{metric}", metric || "a figure");
  }
  return KINDS[step.kind] ?? humanize(step.kind);
}

/** Steps worth a line: what was read and done, not the start, the end or the writing. */
export function visibleSteps(steps: AgentStep[]): AgentStep[] {
  return steps.filter((s) => !["started", "done", "answer"].includes(s.kind));
}

export function stepFailed(step: AgentStep): boolean {
  return step.kind === "failed" || (step.kind === "tool" && step.detail["ok"] === false);
}
