"""Shared API dependencies: engines, the model provider, settings (replaced in tests)."""

from functools import cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine

from app.agent.llm.factory import build_provider
from app.agent.llm.provider import LLMProvider
from app.channels.email import EmailSender, sender_from_settings
from app.config import Settings, get_settings
from app.db import make_engine


@cache
def _engine() -> Engine:
    return make_engine(get_settings().app_database_url)


@cache
def _provider() -> LLMProvider:
    return build_provider(get_settings())


def get_engine() -> Engine:
    return _engine()


def get_provider() -> LLMProvider:
    return _provider()


EngineDep = Annotated[Engine, Depends(get_engine)]
ProviderDep = Annotated[LLMProvider, Depends(get_provider)]


@cache
def _owner_engine() -> Engine:
    return make_engine(get_settings().database_url)


def get_owner_engine() -> Engine:
    """The owner connection: only the admin kill switch uses it (the app role cannot write it)."""
    return _owner_engine()


def get_app_settings() -> Settings:
    return get_settings()


@cache
def _email_sender() -> EmailSender:
    return sender_from_settings(get_settings())


def get_email_sender() -> EmailSender:
    return _email_sender()


OwnerEngineDep = Annotated[Engine, Depends(get_owner_engine)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
