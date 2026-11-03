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

const WEEKDAY = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const TIME_UTC = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
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

/** A calendar day the API names ("2026-09-23"): "Sep 23, 2026". */
export function formatDay(day: string): string {
  const date = instant(`${day}T00:00:00Z`);
  return date ? DAY_YEAR.format(date) : day;
}

/** The last day before a day the API names as an excluded end ("2026-11-30"): "Nov 29, 2026". */
export function formatLastDay(endExclusive: string): string {
  const until = instant(`${endExclusive}T00:00:00Z`);
  return until ? DAY_YEAR.format(new Date(until.getTime() - 1)) : endExclusive;
}

/** A store's calendar day as a heading: "TUE, SEP 15" (upper case is the style's). */
export function formatWeekday(day: string): string {
  const date = instant(`${day}T00:00:00Z`);
  return date ? WEEKDAY.format(date) : day;
}

/** An instant's time of day in the store's time zone: "8:00 AM". */
export function formatTime(at: string, timeZone: string): string {
  const date = instant(at);
  if (!date) return at;
  try {
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      timeZone,
    }).format(date);
  } catch {
    return TIME_UTC.format(date); // an unknown time zone: UTC, rather than nothing
  }
}

/** An instant's calendar day in the store's time zone: a key to group by, and "Mon, Nov 2". */
export function localDay(at: string, timeZone: string): { key: string; label: string } {
  const date = instant(at);
  if (!date) return { key: at, label: at };
  const zoned = (options: Intl.DateTimeFormatOptions) => {
    try {
      return new Intl.DateTimeFormat("en-US", { ...options, timeZone }).formatToParts(date);
    } catch {
      return new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).formatToParts(date);
    }
  };
  const parts = zoned({ year: "numeric", month: "2-digit", day: "2-digit" });
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const label = zoned({ weekday: "short", month: "short", day: "numeric" })
    .map((p) => p.value)
    .join("");
  return { key: `${part("year")}-${part("month")}-${part("day")}`, label };
}
