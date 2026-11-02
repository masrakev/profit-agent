/** Facts shaped like the API's, for tests. */

import type { Fact } from "@/facts/facts";

export const exact: Fact = {
  fact_id: 12,
  metric: "net_profit",
  formula_version: 3,
  kind: "exact",
  status: "defined",
  formatted: "$1,234.50",
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

export const estimate: Fact = {
  ...exact,
  fact_id: 13,
  kind: "estimate",
  formatted: "$5,742.62–$6,469.11",
  value: "6100.0000",
  p10: "5742.6200",
  p50: "6100.0000",
  p90: "6469.1100",
  method: "twin_monte_carlo_v1",
};
