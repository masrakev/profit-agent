"""Versioned system prompts (ADR 0010).

A system prompt is `rules.md` followed by a role file. Prompts are static text: nothing is ever
interpolated into them (store data goes into user-side data blocks), which a test enforces. The
content hash of the composed prompt is its version, recorded in every trace and investigation.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.domain.hashing import sha256_hex

PROMPTS_DIR = Path(__file__).resolve().parent
ROLES = ("investigator", "ask", "classify")
# Only the documented reference syntax may contain braces.
ALLOWED_BRACES = re.compile(r"\{\{F[0-9]+\}\}|\{\{E:(?:store|product:<id>|campaign:<id>)\}\}")


@dataclass(frozen=True)
class Prompt:
    role: str
    text: str
    version: str  # first 16 hex digits of the SHA-256 of `text`

    @property
    def cache_key(self) -> str:
        """Stable prompt_cache_key: requests sharing this prefix route together."""
        return f"{self.role}:{self.version}"


@cache
def load_prompt(role: str) -> Prompt:
    if role not in ROLES:
        raise ValueError(f"unknown prompt role {role!r}")
    rules = (PROMPTS_DIR / "rules.md").read_text(encoding="utf-8").strip()
    body = (PROMPTS_DIR / f"{role}.md").read_text(encoding="utf-8").strip()
    text = f"{rules}\n\n{body}\n"
    leftover = ALLOWED_BRACES.sub("", text)
    if "{" in leftover or "}" in leftover:
        raise ValueError(f"prompt {role!r} contains a placeholder: prompts are static text")
    return Prompt(role, text, sha256_hex(text)[:16])
