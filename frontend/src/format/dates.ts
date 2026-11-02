/**
 * Dates as the owner reads them. The API serves instants (ISO 8601, UTC) and fact periods as
 * half-open intervals [start, end): a period ending at midnight on Sep 28 covers Sep 27 last.
 *
 * The one place the frontend formats with Intl (ADR 0025): dates and times only, never a number.
 */

const DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const DAY_YEAR = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

function instant(text: string): Date | null {
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "Sep 23 – Sep 27, 2026", one day as "Sep 27, 2026", or null for an unreadable period. */
export function formatPeriod(start: string, endExclusive: string): string | null {
  const from = instant(start);
  const until = instant(endExclusive);
  if (!from || !until || until <= from) return null;
  const last = new Date(until.getTime() - 1); // the last instant inside the period
  const lastDay = DAY_YEAR.format(last);
  if (DAY_YEAR.format(from) === lastDay) return lastDay;
  const sameYear = from.getUTCFullYear() === last.getUTCFullYear();
  return `${sameYear ? DAY.format(from) : DAY_YEAR.format(from)} – ${lastDay}`;
}
