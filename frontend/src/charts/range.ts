/**
 * Where an estimate's P10, P50 and P90 sit along a range bar, as fractions of its length.
 *
 * Plotting only: these positions place marks on screen and are never shown as numbers (the bar's
 * labels are the facts' formatted texts). A bar alone spans its own P10 to P90; bars compared on one
 * axis share a domain.
 */

export interface RangeGeometry {
  /** P10, from the start of the axis (0 to 1). */
  low: number;
  /** P50. */
  mark: number;
  /** P90. */
  high: number;
}

export interface Domain {
  min: string;
  max: string;
}

function position(value: number, min: number, max: number): number {
  if (max === min) return 0.5;
  return Math.min(1, Math.max(0, (value - min) / (max - min)));
}

/** The geometry, or null when a value is not a number (it is then shown without a bar). */
export function rangeGeometry(
  p10: string,
  p50: string,
  p90: string,
  domain?: Domain,
): RangeGeometry | null {
  const [low, mid, high] = [Number(p10), Number(p50), Number(p90)];
  const [min, max] = domain ? [Number(domain.min), Number(domain.max)] : [low, high];
  if (![low, mid, high, min, max].every(Number.isFinite) || low > high || min > max) return null;
  return {
    low: position(low, min, max),
    mark: position(mid, min, max),
    high: position(high, min, max),
  };
}

/** The smallest domain holding every range, for bars compared on one axis. */
export function sharedDomain(ranges: readonly { p10: string; p90: string }[]): Domain | null {
  const values = ranges.flatMap((r) => [Number(r.p10), Number(r.p90)]).filter(Number.isFinite);
  if (values.length === 0) return null;
  const lowest = ranges.find((r) => Number(r.p10) === Math.min(...values));
  const highest = ranges.find((r) => Number(r.p90) === Math.max(...values));
  return lowest && highest ? { min: lowest.p10, max: highest.p90 } : null;
}
