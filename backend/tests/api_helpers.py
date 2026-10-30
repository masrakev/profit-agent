"""Callers for API tests: a stand-in principal, so tests about other things need not sign in.
The authentication itself is tested in test_auth.py, through the real flow."""

from uuid import UUID

from fastapi import FastAPI

from app.api.auth import get_principal
from app.auth.service import Principal


class AnyStore(frozenset[UUID]):
    """Every store id is in it: for tests whose subject is not access control."""

    def __contains__(self, item: object) -> bool:
        return True


def act_as(app: FastAPI, *stores: UUID, label: str = "owner:test") -> Principal:
    """Every request is made by a caller who sees `stores` (all stores when none is given)."""
    principal = Principal(
        kind="token",
        store_ids=frozenset(stores) if stores else AnyStore(),
        label=label,
    )
    app.dependency_overrides[get_principal] = lambda: principal
    return principal
