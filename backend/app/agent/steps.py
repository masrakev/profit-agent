"""The agent's step trace: what a session did, step by step, for whoever is listening.

`run_session` reports each model call, tool call, regeneration and answer to the current sink
(a context variable, so callers set it without passing it through every function, and a
thread started with the caller's context keeps it). Nobody listening: nothing happens. A sink
that fails never breaks the agent.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.observability import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Step:
    """`kind`: started, model, tool, regeneration, answer, stopped, cache_hit, done, failed."""

    kind: str
    name: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


Sink = Callable[[Step], None]
_sink: ContextVar[Sink | None] = ContextVar("agent_step_sink", default=None)


def emit(step: Step) -> None:
    sink = _sink.get()
    if sink is None:
        return
    try:
        sink(step)
    except Exception:  # a trace must never stop an investigation
        log.warning("agent.step_not_recorded", kind=step.kind, exc_info=True)


@contextmanager
def recording(sink: Sink) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)
