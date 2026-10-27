"""Canonical JSON and SHA-256, shared by fact hashes and the audit-log chain.

Floats are rejected: their JSON text does not survive a round trip through `jsonb` unchanged,
and money must never be a float anyway. Use `Decimal` (serialized as a string) instead.
"""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def normalize(value: Any) -> Any:
    """Convert a value to plain JSON types with one canonical representation."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, Enum):
        return normalize(value.value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError("floats are not allowed in hashed payloads; use Decimal")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("naive datetimes are not allowed; use UTC")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("object keys must be strings")
            out[key] = normalize(item)
        return out
    if isinstance(value, list | tuple):
        return [normalize(item) for item in value]
    raise TypeError(f"unsupported type in hashed payload: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
