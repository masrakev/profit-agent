"""Facts behind a briefing: computed or loaded, persisted with an id, and recorded as cited."""

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection

from app.agent.tools.derived import compute, mean
from app.domain.hashing import canonical_json, sha256_hex
from app.facts.engine import FactEngine
from app.facts.model import Fact, FactKind, FactStatus, Lineage, ParentRef, Period, Scope, Unit
from app.facts.repository import get_facts

STAKE_FORMULA = ("briefing.money_at_stake", 1)
STAKE_METHOD = "sum_of_quantiles_v1"
LOSS_FORMULA = ("briefing.monthly_loss", 1)


class Cited:
    """Use inside the store's tenant transaction. `ref` and `entity` return the references the
    briefing text uses and remember them, so rendering and the verifier know every one."""

    def __init__(self, conn: Connection, store_id: UUID) -> None:
        self.conn = conn
        self.store_id = store_id
        self.engine = FactEngine(conn, store_id)
        self.facts: dict[int, Fact] = {}
        self.entities: set[str] = set()

    def get(self, formula_id: str, scope: Scope, start: date, end: date) -> Fact:
        return self.keep(self.engine.fact(formula_id, scope, Period.days(start, end)))

    def keep(self, fact: Fact) -> Fact:
        saved = self.engine.persist(self.engine.adopt(fact))
        assert saved.id is not None
        self.facts[saved.id] = saved
        return saved

    def load(self, ids: Iterable[int]) -> dict[int, Fact]:
        """Persisted facts (incident impacts, Shapley contributions, simulated changes)."""
        found = get_facts(self.conn, self.store_id, ids, with_lineage=True)
        for fact in found.values():
            self.engine.adopt(fact)
        self.facts.update(found)
        return found

    def ref(self, fact: Fact) -> str:
        assert fact.id is not None
        self.facts[fact.id] = fact
        return f"{{{{F{fact.id}}}}}"

    def entity(self, ref: str) -> str:
        self.entities.add(ref)
        return f"{{{{E:{ref}}}}}"

    def change(self, current: Fact, previous: Fact) -> Fact:
        """`current - previous`, an exact derived fact."""
        assert current.id is not None
        assert previous.id is not None
        return self.keep(
            compute(f"F{current.id} - F{previous.id}", {current.id: current, previous.id: previous})
        )

    def magnitude(self, fact: Fact) -> Fact:
        """The fact itself when it is not negative, else its negation (an exact derived fact):
        a loss is always written as a positive amount with a word that says it is a loss."""
        if fact.value is None or fact.value >= 0:
            return fact
        assert fact.id is not None
        return self.keep(compute(f"-F{fact.id}", {fact.id: fact}))

    def direction(self, fact: Fact) -> str:
        """`up <amount>` or `down <amount>` (`unchanged` when zero; `n/a` when undefined)."""
        if fact.value is None:
            return self.ref(fact)
        if fact.value == 0:
            return f"unchanged ({self.ref(fact)})"
        word = "up" if fact.value > 0 else "down"
        return f"{word} {self.ref(self.magnitude(fact))}"

    def gain_or_loss(self, fact: Fact) -> str:
        """`gained <amount>` or `lost <amount>`."""
        if fact.value is None:
            return self.ref(fact)
        word = "gained" if fact.value >= 0 else "lost"
        return f"{word} {self.ref(self.magnitude(fact))}"

    def amount(self, fact: Fact) -> str:
        """A money level, `lost <amount>` when negative (a campaign's profit, say)."""
        if fact.value is None or fact.value >= 0:
            return self.ref(fact)
        return f"lost {self.ref(self.magnitude(fact))}"

    def average(self, parts: Sequence[Fact], start: date, end: date) -> Fact:
        return self.keep(mean(parts, Period.days(start, end), parts[0]))

    def loss(self, impact: Fact) -> Fact | None:
        """A negative expected impact as a positive monthly loss: P10, P50 and P90 negated (the
        range reversed), so a loss reads as an amount, not a negative range."""
        if not impact.is_defined or impact.p10 is None or impact.p50 is None or impact.p90 is None:
            return None
        if impact.p50 >= 0:
            return None
        return self._estimate(
            LOSS_FORMULA,
            [("impact", impact)],
            (-impact.p90, -impact.p50, -impact.p10),
            f"negated:{impact.method}",
            impact.period,
        )

    def stake(self, losses: Sequence[Fact], start: date, end: date) -> Fact | None:
        """The open problems' monthly losses added up: P10, P50 and P90 each summed, the range
        they would have if the problems moved together (the widest, not the narrower range that
        independence would give)."""
        if not losses:
            return None
        sums = tuple(
            sum((getattr(f, q) for f in losses), Decimal(0)) for q in ("p10", "p50", "p90")
        )
        return self._estimate(
            STAKE_FORMULA,
            [(f"loss:{i}", f) for i, f in enumerate(losses)],
            (sums[0], sums[1], sums[2]),
            STAKE_METHOD,
            Period.days(start, end),
        )

    def _estimate(
        self,
        formula: tuple[str, int],
        parents: Sequence[tuple[str, Fact]],
        quantiles: tuple[Decimal, Decimal, Decimal],
        method: str,
        period: Period,
    ) -> Fact:
        fact = Fact(
            store_id=self.store_id,
            formula_id=formula[0],
            formula_version=formula[1],
            kind=FactKind.ESTIMATE,
            scope=Scope.store(),
            period=period,
            status=FactStatus.DEFINED,
            value=quantiles[1],
            p10=quantiles[0],
            p50=quantiles[1],
            p90=quantiles[2],
            method=method,
            unit=Unit.MONEY,
            currency=parents[0][1].currency,
            inputs_hash=sha256_hex(
                canonical_json({"method": method, "parents": [f.fact_hash for _, f in parents]})
            ),
            lineage=Lineage(
                parents=tuple(ParentRef(role=r, fact_hash=f.fact_hash) for r, f in parents)
            ),
        )
        return self.keep(fact)
