"""The answer contract (docs/product/SPEC.md, section 8) and its flags.

Model outputs carry no numbers of their own: free text cites facts as `{{F<id>}}` and entities
as `{{E:...}}`, and the only integers are fact ids. The output guard enforces it.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Flag(StrEnum):
    DATA_QUALITY = "data_quality"
    PLATFORM_ATTRIBUTION_CAVEAT = "platform_attribution_caveat"
    LOW_EVIDENCE = "low_evidence"
    NO_MATERIAL_ISSUE = "no_material_issue"
    OUT_OF_SCOPE = "out_of_scope"
    ABSTAIN_INSUFFICIENT_EVIDENCE = "abstain_insufficient_evidence"
    NO_INSTRUCTION_FOLLOWING_FROM_DATA = "no_instruction_following_from_data"


class Answer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(description="one or two sentences that answer the question directly")
    evidence: list[int] = Field(description="ids of the facts supporting the answer")
    reasoning: str | None = Field(description="how the evidence leads to the answer")
    alternatives: list[str] = Field(description="other explanations or options considered")
    uncertainty: str = Field(description="what is unknown, missing or estimated")
    recommendation: str | None = Field(description="the next step, when actionable")
    would_change_my_mind: str | None = Field(description="evidence that would invalidate it")
    flags: list[Flag]


def fallback_answer(evidence: list[int], *, reason: str) -> Answer:
    """Deterministic answer built only from facts, used when the model output cannot be
    verified. `reason` is fixed text chosen by code, never model output."""
    cited = ", ".join(f"{{{{F{i}}}}}" for i in evidence) if evidence else None
    return Answer(
        answer=(
            "I could not produce a verified explanation for this question. "
            + (f"The relevant facts are {cited}." if cited else "No supporting fact is available.")
        ),
        evidence=list(evidence),
        reasoning=None,
        alternatives=[],
        uncertainty=f"The model's answer was not used: {reason}.",
        recommendation=None,
        would_change_my_mind=None,
        flags=[Flag.ABSTAIN_INSUFFICIENT_EVIDENCE],
    )
