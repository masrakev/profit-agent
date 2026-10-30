"""Cursor pagination: `?limit=` (1-200, default 50) and `?cursor=` from the previous page.

A page is `{"items": [...], "next_cursor": "..."}`; `next_cursor` is null on the last page. The
cursor is opaque (the sort key of the last item, base64url JSON): pages stay stable when new
items arrive at the head.
"""

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from typing import Annotated

from fastapi import HTTPException, Query
from pydantic import BaseModel

Limit = Annotated[int, Query(ge=1, le=200, description="items per page")]
Cursor = Annotated[
    str | None, Query(max_length=500, description="next_cursor of the previous page")
]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def _encode(key: Sequence[str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(list(key)).encode()).decode().rstrip("=")


def _decode(cursor: str) -> list[str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        key = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        key = None
    if not isinstance(key, list) or not all(isinstance(k, str) for k in key):
        raise HTTPException(
            status_code=422, detail={"code": "invalid_cursor", "message": "invalid cursor"}
        )
    return key


def paginate[T](
    items: Sequence[T],
    *,
    key: Callable[[T], Sequence[str]],
    limit: int,
    cursor: str | None,
    descending: bool = True,
) -> Page[T]:
    """`items` sorted by `key` (newest first when `descending`), one page of them."""
    ordered = sorted(items, key=lambda i: list(key(i)), reverse=descending)
    if cursor is not None:
        after = _decode(cursor)
        ordered = [
            i for i in ordered if (list(key(i)) < after if descending else list(key(i)) > after)
        ]
    chunk = ordered[:limit]
    more = len(ordered) > limit
    return Page[T](items=chunk, next_cursor=_encode(key(chunk[-1])) if more and chunk else None)
