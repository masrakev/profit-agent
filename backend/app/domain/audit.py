"""Append-only, hash-chained audit log (one chain per store).

Each entry stores the SHA-256 of the previous entry (`prev_hash`) and its own hash over its
canonical content. The application role has no UPDATE or DELETE privilege on `audit_log`; the chain
additionally makes any out-of-band edit, deletion or reordering detectable by `verify_chain`.
Truncating the newest entries is only detectable against an externally anchored head hash.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, insert, select, text

from app.domain.hashing import canonical_json, normalize, sha256_hex
from app.domain.models import AuditLogEntry
from app.domain.schema import audit_log

GENESIS_HASH = "0" * 64


def compute_entry_hash(
    *,
    store_id: UUID,
    seq: int,
    occurred_at: datetime,
    actor: str,
    action: str,
    payload: dict[str, Any],
    prev_hash: str,
) -> str:
    return sha256_hex(
        canonical_json(
            {
                "store_id": store_id,
                "seq": seq,
                "occurred_at": occurred_at,
                "actor": actor,
                "action": action,
                "payload": payload,
                "prev_hash": prev_hash,
            }
        )
    )


def append_audit(
    conn: Connection,
    store_id: UUID,
    *,
    actor: str,
    action: str,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> AuditLogEntry:
    """Append one entry. Must run inside the store's tenant transaction."""
    # Serialize appends per store so two writers cannot both extend the same head.
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"audit_log:{store_id}"},
    )
    head = conn.execute(
        select(audit_log.c.seq, audit_log.c.entry_hash)
        .where(audit_log.c.store_id == store_id)
        .order_by(audit_log.c.seq.desc())
        .limit(1)
    ).first()
    seq = 1 if head is None else int(head.seq) + 1
    prev_hash = GENESIS_HASH if head is None else str(head.entry_hash)
    when = (occurred_at or datetime.now(UTC)).astimezone(UTC)
    clean_payload: dict[str, Any] = normalize(payload)
    entry_hash = compute_entry_hash(
        store_id=store_id,
        seq=seq,
        occurred_at=when,
        actor=actor,
        action=action,
        payload=clean_payload,
        prev_hash=prev_hash,
    )
    conn.execute(
        insert(audit_log).values(
            store_id=store_id,
            seq=seq,
            occurred_at=when,
            actor=actor,
            action=action,
            payload=clean_payload,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
    )
    return AuditLogEntry(
        store_id=store_id,
        seq=seq,
        occurred_at=when,
        actor=actor,
        action=action,
        payload=clean_payload,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )


@dataclass(frozen=True)
class ChainVerification:
    valid: bool
    entries_checked: int
    first_invalid_seq: int | None = None
    reason: str | None = None


def verify_chain(conn: Connection, store_id: UUID) -> ChainVerification:
    rows = conn.execute(
        select(audit_log).where(audit_log.c.store_id == store_id).order_by(audit_log.c.seq)
    ).all()
    expected_prev = GENESIS_HASH
    for index, row in enumerate(rows, start=1):
        if int(row.seq) != index:
            return ChainVerification(False, index - 1, int(row.seq), f"expected seq {index}")
        if row.prev_hash != expected_prev:
            return ChainVerification(False, index - 1, index, "prev_hash does not match")
        recomputed = compute_entry_hash(
            store_id=row.store_id,
            seq=int(row.seq),
            occurred_at=row.occurred_at,
            actor=row.actor,
            action=row.action,
            payload=row.payload,
            prev_hash=row.prev_hash,
        )
        if recomputed != row.entry_hash:
            return ChainVerification(False, index - 1, index, "entry_hash does not match content")
        expected_prev = row.entry_hash
    return ChainVerification(True, len(rows))
