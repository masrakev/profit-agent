"""Read-only, typed tools for the agent (ADR 0010)."""

from app.agent.tools.audit import AUDIT_TOOLS
from app.agent.tools.base import ToolContext, ToolOutcome, ToolRegistry
from app.agent.tools.catalog import TOOLS

ALL_TOOLS = [*TOOLS, *AUDIT_TOOLS]


def build_registry() -> ToolRegistry:
    return ToolRegistry(list(ALL_TOOLS))


__all__ = [
    "ALL_TOOLS",
    "AUDIT_TOOLS",
    "TOOLS",
    "ToolContext",
    "ToolOutcome",
    "ToolRegistry",
    "build_registry",
]
