/** Facts shaped like the API's, for tests. */

import type { Fact } from "@/facts/facts";

export const exact: Fact = {
  fact_id: 12,
  metric: "net_profit",
  name: "Net profit",
  formula_version: 3,
  kind: "exact",
  status: "defined",
  formatted: "$1,234.50",
  display: "$1,235",
  change: false,
  value: "1234.5000",
  unit: "money",
  currency: "USD",
  scope: "store",
  period_start: "2026-09-01T00:00:00Z",
  period_end: "2026-09-08T00:00:00Z",
  p10: null,
  p50: null,
  p90: null,
};

const text = (formatted: string, display: string) => ({ formatted, display });

/** An estimate as the API serves it: raw quantiles to plot, and their texts to show. */
export function estimateFact(
  fact_id: number,
  [p10, p50, p90]: [string, string, string],
  [f10, f50, f90]: [string, string, string],
  [d10, d50, d90]: [string, string, string],
  change = false,
): Fact {
  return {
    ...exact,
    fact_id,
    kind: "estimate",
    formatted: `${f10}–${f90}`,
    display: `${d10} to ${d90}`,
    change,
    quantiles: { p10: text(f10, d10), p50: text(f50, d50), p90: text(f90, d90) },
    value: p50,
    p10,
    p50,
    p90,
    method: "twin_monte_carlo_v1",
    method_description: "simulated by the store twin",
  };
}

export const estimate = estimateFact(
  13,
  ["5742.6200", "6100.0000", "6469.1100"],
  ["$5,742.62", "$6,100.00", "$6,469.11"],
  ["$5,743", "$6,100", "$6,469"],
);
