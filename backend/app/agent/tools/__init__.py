"""Read-only, typed tools for the agent (ADR 0010)."""

from app.agent.tools.base import ToolContext, ToolOutcome, ToolRegistry
from app.agent.tools.catalog import TOOLS


def build_registry() -> ToolRegistry:
    return ToolRegistry(list(TOOLS))


__all__ = ["TOOLS", "ToolContext", "ToolOutcome", "ToolRegistry", "build_registry"]
