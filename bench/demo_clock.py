"""The demo's clock: the store's day, not the wall's.

The demo store's data ends on a fixed day (its scenario); the morning brief is dated the day
after. Everything the seed and the demo servers do (the goal set, the past decisions, the alert
and its decision, the owner's approvals, the executions, the conversations) is stamped on that
same calendar: 07:00 for what the seed does on a day; the demo servers keep the wall's time of
day on the store's date (whole days back; eight hours later before 08:00, so that nothing comes
before the seed's morning), so that every process of the demo (API, executor, WhatsApp worker)
reads the same clock however far apart they started; only processes started on either side of
08:00 on the wall would not. Without it the brief says September while the decisions say the
day the seed ran.

The clock moves for this process only (time-machine): the database's own `now()` is not used for
anything shown.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta

import time_machine
from sqlalchemy import Engine, text

SEEDS_AT = time(7, 0)  # what the seed does on a store day
BRIEF_AT = time(8, 0)  # the morning brief: the demo runs after it
EARLY_SHIFT = timedelta(hours=8)


def at(day: date, moment: time) -> datetime:
    """A moment of a store day (the demo store keeps UTC)."""
    return datetime.combine(day, moment, tzinfo=UTC)


def store_today(engine: Engine) -> date | None:
    """The demo store's today: the day after its last order (None before a seed)."""
    with engine.connect() as conn:
        today: date | None = conn.execute(
            text("SELECT max(ordered_at)::date + 1 FROM orders")
        ).scalar_one()
    return today


def on_store_date(today: date, now: datetime | None = None) -> datetime:
    """The wall's moment moved to the store's date, by whole days; before 08:00 on the wall, eight
    hours later too, so that the demo never runs before the seed's 07:00 and the 08:00 brief."""
    now = now or datetime.now(UTC)
    moved = now + timedelta(days=(today - now.date()).days)
    return moved + EARLY_SHIFT if moved.time() < BRIEF_AT else moved


@contextmanager
def travel(when: datetime) -> Iterator[None]:
    """Run with the clock set to `when`, running on from there."""
    with time_machine.travel(when, tick=True):
        yield
