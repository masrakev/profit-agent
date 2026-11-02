/** API-shaped data for the conversation's tests. */

import { estimate, estimateFact, exact } from "@/test/facts";
import { STORE_ID } from "@/test/render";

export const PRODUCT = "ea63836b-e0d7-5298-b9db-b58631ed27f1";
export const CAMPAIGN = "6433a313-4edd-55d2-a5f8-baf1fc04ed95";
export const INCIDENT = "inc-0806cd14e96b";
export const DECISION = "e8e97d58-25dc-4f79-b1af-7acc5f571411";
export const INVESTIGATION = "08949273-ed00-45ec-81d3-f868cb657e14";

export const NAMES = {
  store: "Northwind Outdoor",
  [`product:${PRODUCT}`]: "Trail Jacket",
  [`campaign:${CAMPAIGN}`]: "Trail Jacket — Prospecting",
};

export const impact = estimateFact(
  21,
  ["613.18", "634.40", "654.33"],
  ["$613.18", "$634.40", "$654.33"],
  ["+$613", "+$634", "+$654"],
  true,
);
export const zero = {
  ...exact,
  fact_id: 22,
  metric: "decision.do_nothing.net_profit",
  name: "Change in net profit from doing nothing",
  formatted: "$0.00",
  display: "$0",
  change: true,
  period_start: "2026-09-15T00:00:00Z",
  period_end: "2026-09-29T00:00:00Z",
};

export const BRIEFING = {
  briefing_id: "921b13c0-5c03-4a2c-8a8d-4b07038a9edf",
  kind: "daily",
  local_date: "2026-09-15",
  period_start: "2026-09-14",
  period_end: "2026-09-15",
  status: "narrated",
  headline: "A critical problem needs your attention today.",
  created_at: "2026-09-15T08:00:00Z",
  narrative: `{{E:product:${PRODUCT}}} keeps spending while out of stock.`,
  sections: [
    {
      key: "health",
      title: "Health",
      items: [{ text: "Net profit this week {{F12}}.", buttons: [] }],
    },
    {
      key: "money_at_stake",
      title: "Money at stake",
      items: [{ text: "About {{F13}} a month across open problems.", buttons: [] }],
    },
    {
      key: "top_items",
      title: "Top items",
      items: [
        {
          text: `{{E:product:${PRODUCT}}}: ads keep spending on a product that is out of stock.`,
          level: "critical",
          decision_id: DECISION,
          incident_id: INCIDENT,
          buttons: [],
        },
      ],
    },
    {
      key: "pending_decisions",
      title: "Pending decisions",
      items: [
        {
          text: `{{E:campaign:${CAMPAIGN}}}: raise the daily budget, within the cap.`,
          decision_id: "d-2",
          buttons: [],
        },
      ],
    },
    {
      key: "data_notice",
      title: "Data notice",
      items: [{ text: "Data stops before yesterday.", buttons: [] }],
    },
    { key: "watch", title: "Watchlist", empty: "Nothing to watch.", items: [] },
  ],
  facts: { "12": exact, "13": estimate },
  names: NAMES,
};

export const ANSWER = {
  ask_id: "a1",
  store_id: STORE_ID,
  question: "What should I do about the jacket?",
  status: "answered",
  answer: {
    answer: `Pause {{E:campaign:${CAMPAIGN}}}: it spent {{F12}} with nothing to sell.`,
    evidence: [12, 99],
    reasoning: "The stock of {{E:product:" + PRODUCT + "}} is zero.",
    alternatives: ["Cut the budget instead."],
    uncertainty: "When the stock arrives.",
    recommendation: "Pause until restock, expected {{F21}}.",
    would_change_my_mind: "A restock this week.",
    flags: ["platform_attribution_caveat"],
    ranked_causes: [],
  },
  facts: { "12": exact, "21": impact },
  names: NAMES,
};

export function option(id: string, label: string, factId: number | null, actions: unknown[] = []) {
  return {
    option_id: id,
    label,
    rank: 0,
    kind: "pause_until_restock",
    action_family: "pause_or_reduce_campaign",
    entity: `product:${PRODUCT}`,
    actions,
    executable: actions.length > 0,
    reversibility: actions.length > 0 ? "reversible" : "prepare_only",
    impact_fact_id: factId,
    p10: null,
    p50: null,
    p90: null,
    risks: [],
    invalidated_if: [],
    flags: [],
  };
}

export function decision(status: string, extra: Record<string, unknown> = {}) {
  return {
    decision_id: DECISION,
    store_id: STORE_ID,
    source: "incident",
    incident_id: INCIDENT,
    cause: "stockout_on_promoted",
    entity: `product:${PRODUCT}`,
    status,
    recommended_option_id: "pause",
    approved_option_id: status === "proposed" ? null : "pause",
    horizon_days: 14,
    floor: "46.67",
    currency: "USD",
    as_of: "2026-09-15",
    expires_at: "2026-11-05T00:00:00Z",
    created_at: "2026-11-02T00:00:00Z",
    updated_at: "2026-11-02T00:00:00Z",
    label: "Pause ‘Trail Jacket — Prospecting’ until restock?",
    do_nothing: { label: "Do nothing", impact_fact_id: 22 },
    options: [
      option("pause", "Pause ‘Trail Jacket — Prospecting’ until restock", 21, [
        { kind: "pause_campaign", entity: CAMPAIGN, change: "0", days: 14 },
      ]),
      option("reorder", "Prepare a reorder of Trail Jacket", null),
    ],
    superseded_by: null,
    superseded_reason: null,
    ...extra,
  };
}
