"""The demo's clock (bench/demo_clock.py): the wall's time of day on the store's date, the same
for every process however far apart they start, and the seed's moments on store days."""

from datetime import UTC, date, datetime, time

from bench import demo_clock as clock


def test_the_store_date_keeps_the_time_of_day() -> None:
    wall = datetime(2026, 11, 3, 17, 26, 5, tzinfo=UTC)
    moved = clock.on_store_date(date(2026, 9, 15), wall)
    assert moved == datetime(2026, 9, 15, 17, 26, 5, tzinfo=UTC)
    # Two processes started minutes apart read the same clock.
    later = clock.on_store_date(date(2026, 9, 15), datetime(2026, 11, 3, 17, 40, tzinfo=UTC))
    assert (later - moved).total_seconds() == 835


def test_before_the_brief_the_demo_runs_after_it() -> None:
    night = datetime(2026, 11, 4, 0, 40, tzinfo=UTC)
    assert clock.on_store_date(date(2026, 9, 15), night) == datetime(2026, 9, 15, 8, 40, tzinfo=UTC)


def test_travel_sets_the_clock_and_lets_it_run() -> None:
    start = clock.at(date(2026, 9, 15), clock.SEEDS_AT)
    assert start == datetime.combine(date(2026, 9, 15), time(7, 0), tzinfo=UTC)
    with clock.travel(start):
        now = datetime.now(UTC)
        assert start <= now < start.replace(minute=1)
    assert datetime.now(UTC) > start  # the wall clock again, past the store's day
