"""Runtime guard: while a tool runs, the connection may write facts and nothing else.

Tools derive facts (append-only, hashed, with lineage) but never business data. Every
statement SQLAlchemy sends is inspected; a write to any other table raises before it reaches
the database. (Fact lineage rows are written through the raw driver cursor inside the fact
repository, which only ever targets `fact_lineage`.)
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, event

FACT_TABLES = frozenset({"facts", "fact_lineage"})
_WRITE = re.compile(
    r"^\s*(?:with\b.*?\)\s*)?(insert\s+into|update|delete\s+from|merge\s+into|truncate"
    r"|alter|drop|create|grant|revoke|copy)\s+(?:table\s+)?(?:only\s+)?\"?(\w+)",
    re.IGNORECASE | re.DOTALL,
)


class WriteForbiddenError(PermissionError):
    pass


def _check(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
    match = _WRITE.match(statement)
    if match is None:
        return
    verb, table = match.group(1).lower(), match.group(2).lower()
    if verb.startswith("insert") and table in FACT_TABLES:
        return
    raise WriteForbiddenError(f"tools are read-only: {verb} on {table!r} refused")


@contextmanager
def facts_only(conn: Connection) -> Iterator[Connection]:
    event.listen(conn, "before_cursor_execute", _check)
    try:
        yield conn
    finally:
        event.remove(conn, "before_cursor_execute", _check)
