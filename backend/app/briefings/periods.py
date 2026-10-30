"""The data days each briefing covers (SPEC sections 4 and 5).

A briefing covers complete days of data up to the store's local yesterday. Data days are UTC
calendar days, as for every fact. When data stops earlier (a stale source, or a synthetic store),
the briefing covers the last complete period of the data instead, and the daily brief's data
notice says the data is behind.
"""

from datetime import date, timedelta


def last_day(data_end: date, local_today: date) -> date:
    """The latest day that has data and is before the store's local today (`data_end` is the
    day after the last day of data)."""
    return min(data_end, local_today) - timedelta(days=1)


def day_period(day: date) -> tuple[date, date]:
    return day, day + timedelta(days=1)


def week_period(day: date) -> tuple[date, date]:
    """The last complete Monday to Sunday week ending on or before `day`."""
    end = (
        day + timedelta(days=1) if day.isoweekday() == 7 else day - timedelta(day.isoweekday() - 1)
    )
    return end - timedelta(days=7), end


def month_period(day: date) -> tuple[date, date]:
    """The last complete calendar month ending on or before `day`."""
    if (day + timedelta(days=1)).day == 1:
        return day.replace(day=1), day + timedelta(days=1)
    end = day.replace(day=1)
    return (end - timedelta(days=1)).replace(day=1), end


def previous(period: tuple[date, date], *, monthly: bool = False) -> tuple[date, date]:
    """The period of the same length just before (the calendar month before, when monthly)."""
    start, end = period
    if monthly:
        return month_period(start - timedelta(days=1))
    return start - (end - start), start
