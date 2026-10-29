"""Budget guard: refuses a call *before* it is made when it could exceed a spending cap.

Each call first reserves its worst-case cost (every input token uncached, every output token
used); after the call the reservation is settled to the actual cost. Reservation and check
happen atomically under the ledger's lock, so concurrent workers sharing a ledger file cannot
overshoot a cap together. A crashed call leaves its reservation counted (conservative).

Caps: per run (an investigation, a benchmark run), per UTC day, and optionally in total (for
example the hard cap of a task).
"""

import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.agent.llm.errors import BudgetExceededError


@dataclass(frozen=True)
class SpendEntry:
    entry_id: str
    day: date
    run_id: str
    model: str
    amount: Decimal  # a reservation, or a (negative or positive) settlement adjustment
    kind: str  # "reserve" | "settle"


class SpendLedger(Protocol):
    @contextmanager
    def locked(self) -> Iterator[list[SpendEntry]]:
        """Exclusive access: yields the current entries; entries appended through `append`
        while locked are written before the lock is released."""
        ...

    def append(self, entry: SpendEntry) -> None: ...


class InMemorySpendLedger:
    def __init__(self) -> None:
        self._entries: list[SpendEntry] = []
        self._lock = threading.Lock()

    @contextmanager
    def locked(self) -> Iterator[list[SpendEntry]]:
        with self._lock:
            yield list(self._entries)

    def append(self, entry: SpendEntry) -> None:
        self._entries.append(entry)


class JsonlSpendLedger:
    """Append-only JSON lines file shared by processes, guarded by a lock file."""

    def __init__(self, path: Path, *, lock_timeout: float = 10.0) -> None:
        self.path = path
        self._lock_path = path.with_suffix(path.suffix + ".lock")
        self._lock_timeout = lock_timeout
        self._pending: list[SpendEntry] = []

    @contextmanager
    def locked(self) -> Iterator[list[SpendEntry]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._lock_timeout
        while True:
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except (FileExistsError, PermissionError):
                # Windows reports PermissionError while the lock file is being deleted by
                # another holder ("delete pending"): the lock is still taken, wait.
                if time.monotonic() > deadline:
                    raise TimeoutError(f"spend ledger lock {self._lock_path} is held") from None
                time.sleep(0.01)
        try:
            self._pending = []
            yield self._read()
            if self._pending:
                with self.path.open("a", encoding="utf-8") as f:
                    for e in self._pending:
                        f.write(json.dumps(_to_json(e)) + "\n")
        finally:
            self._pending = []
            os.close(fd)
            os.unlink(self._lock_path)

    def append(self, entry: SpendEntry) -> None:
        self._pending.append(entry)

    def _read(self) -> list[SpendEntry]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [_from_json(json.loads(line)) for line in f if line.strip()]


def _to_json(e: SpendEntry) -> dict[str, str]:
    return {
        "entry_id": e.entry_id,
        "day": e.day.isoformat(),
        "run_id": e.run_id,
        "model": e.model,
        "amount": str(e.amount),
        "kind": e.kind,
    }


def _from_json(d: dict[str, str]) -> SpendEntry:
    return SpendEntry(
        d["entry_id"],
        date.fromisoformat(d["day"]),
        d["run_id"],
        d["model"],
        Decimal(d["amount"]),
        d["kind"],
    )


@dataclass(frozen=True)
class BudgetCaps:
    per_run_usd: Decimal
    daily_usd: Decimal
    total_usd: Decimal | None = None


@dataclass(frozen=True)
class Reservation:
    entry_id: str
    day: date
    run_id: str
    model: str
    amount: Decimal


@dataclass(frozen=True)
class SpendSummary:
    run: Decimal
    day: Decimal
    total: Decimal


class BudgetGuard:
    def __init__(
        self,
        caps: BudgetCaps,
        ledger: SpendLedger,
        *,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self.caps = caps
        self.ledger = ledger
        self._today = today

    def reserve(self, run_id: str, model: str, upper_bound: Decimal) -> Reservation:
        day = self._today()
        with self.ledger.locked() as entries:
            spent = _summary(entries, run_id, day)
            for label, used, cap in (
                ("per-run", spent.run, self.caps.per_run_usd),
                ("daily", spent.day, self.caps.daily_usd),
                ("total", spent.total, self.caps.total_usd),
            ):
                if cap is not None and used + upper_bound > cap:
                    raise BudgetExceededError(
                        f"{label} cap {cap} USD: {used} already spent or reserved, this call "
                        f"could cost up to {upper_bound} USD; not calling the model"
                    )
            reservation = Reservation(uuid4().hex, day, run_id, model, upper_bound)
            self.ledger.append(
                SpendEntry(reservation.entry_id, day, run_id, model, upper_bound, "reserve")
            )
        return reservation

    def settle(self, reservation: Reservation, actual: Decimal) -> None:
        """Replace the reservation by the actual cost (zero when the call produced nothing
        billable, e.g. it failed before reaching the model)."""
        with self.ledger.locked():
            self.ledger.append(
                SpendEntry(
                    reservation.entry_id,
                    reservation.day,
                    reservation.run_id,
                    reservation.model,
                    actual - reservation.amount,
                    "settle",
                )
            )

    def spent(self, run_id: str) -> SpendSummary:
        with self.ledger.locked() as entries:
            return _summary(entries, run_id, self._today())


def _summary(entries: list[SpendEntry], run_id: str, day: date) -> SpendSummary:
    total = sum((e.amount for e in entries), Decimal(0))
    return SpendSummary(
        run=sum((e.amount for e in entries if e.run_id == run_id), Decimal(0)),
        day=sum((e.amount for e in entries if e.day == day), Decimal(0)),
        total=total,
    )
