from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, text

from app.db import tenant_transaction
from app.domain.audit import GENESIS_HASH, append_audit, verify_chain
from app.domain.hashing import canonical_json
from app.domain.schema import metadata
from tests.conftest import create_store

pytestmark = pytest.mark.db


def _chain(app_engine: Engine, entries: int = 3):  # type: ignore[no-untyped-def]
    store = create_store(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        for i in range(entries):
            append_audit(
                conn,
                store,
                actor="test",
                action=f"step.{i}",
                payload={"amount": Decimal("12.3400"), "i": i, "nested": {"ok": True}},
            )
    return store


def test_chain_links_and_verifies(app_engine: Engine) -> None:
    store = _chain(app_engine)
    with tenant_transaction(app_engine, store) as conn:
        result = verify_chain(conn, store)
        rows = conn.execute(
            text(
                "SELECT seq, prev_hash, entry_hash FROM audit_log WHERE store_id = :s ORDER BY seq"
            ),
            {"s": store},
        ).all()
    assert result.valid
    assert result.entries_checked == 3
    assert rows[0].prev_hash == GENESIS_HASH
    assert rows[1].prev_hash == rows[0].entry_hash
    assert rows[2].prev_hash == rows[1].entry_hash


def test_appended_entry_survives_session_timezone(app_engine: Engine) -> None:
    store = _chain(app_engine, 1)
    with tenant_transaction(app_engine, store) as conn:
        conn.execute(text("SET LOCAL TimeZone = 'Asia/Kolkata'"))
        assert verify_chain(conn, store).valid


@pytest.mark.parametrize(
    ("tamper", "seq", "reason"),
    [
        (
            "UPDATE audit_log SET payload = jsonb_set(payload, '{i}', '7') "
            "WHERE store_id = :s AND seq = 2",
            2,
            "entry_hash",
        ),
        (
            "UPDATE audit_log SET occurred_at = occurred_at + interval '1 second' "
            "WHERE store_id = :s AND seq = 1",
            1,
            "entry_hash",
        ),
        ("DELETE FROM audit_log WHERE store_id = :s AND seq = 2", 3, "expected seq 2"),
    ],
)
def test_tampering_is_detected(
    app_engine: Engine, owner_engine: Engine, tamper: str, seq: int, reason: str
) -> None:
    store = _chain(app_engine)
    with owner_engine.begin() as conn:  # an attacker with owner access, bypassing grants
        conn.execute(text(tamper), {"s": store})
    with tenant_transaction(app_engine, store) as conn:
        result = verify_chain(conn, store)
    assert not result.valid
    assert result.first_invalid_seq == seq
    assert reason in (result.reason or "")


def test_relinked_chain_with_forged_hashes_is_detected(
    app_engine: Engine, owner_engine: Engine
) -> None:
    store = _chain(app_engine)
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE audit_log SET prev_hash = repeat('1', 64) WHERE store_id = :s AND seq = 3"
            ),
            {"s": store},
        )
    with tenant_transaction(app_engine, store) as conn:
        result = verify_chain(conn, store)
    assert (result.valid, result.first_invalid_seq, result.reason) == (
        False,
        3,
        "prev_hash does not match",
    )


def test_hashed_payloads_reject_floats_and_naive_datetimes() -> None:
    with pytest.raises(TypeError, match="floats"):
        canonical_json({"x": 1.5})
    with pytest.raises(TypeError, match="naive"):
        canonical_json({"x": datetime(2026, 1, 1)})  # noqa: DTZ001
    with pytest.raises(TypeError, match="keys"):
        canonical_json({1: "x"})
    with pytest.raises(TypeError, match="unsupported"):
        canonical_json({"x": object()})
    assert canonical_json({"b": 1, "a": datetime(2026, 1, 1, tzinfo=UTC)}) == (
        '{"a":"2026-01-01T00:00:00+00:00","b":1}'
    )


def test_schema_module_matches_migrations(owner_engine: Engine) -> None:
    """Tables, columns, types and nullability in `schema.py` match the migrated database."""
    with owner_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(context, metadata)
    column_level = [
        d
        for d in diff
        if (d[0] if isinstance(d, tuple) else d[0][0])
        in {
            "add_table",
            "remove_table",
            "add_column",
            "remove_column",
            "modify_type",
            "modify_nullable",
        }
    ]
    assert column_level == []
