"""Pydantic v2 schemas for all LLM input and output.

Every model uses extra="forbid" so unexpected fields from the LLM are caught
before they reach any business logic.

These schema names and field names are stable -- later steps depend on them.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ExtractedAction(BaseModel, extra="forbid"):
    """One action item extracted from meeting notes by the LLM."""

    description: str = Field(..., min_length=1)
    owner: str | None = None
    due_text: str | None = None
    source_line: int = Field(..., ge=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_clarification: bool = False
    clarification_question: str | None = None

    @model_validator(mode="after")
    def owner_none_requires_clarification(self) -> "ExtractedAction":
        """When owner is None the LLM must flag it and supply a question."""
        if self.owner is None:
            if not self.needs_clarification:
                raise ValueError("needs_clarification must be True when owner is None")
            if not self.clarification_question:
                raise ValueError("clarification_question must be provided when owner is None")
        return self


class ExtractionResult(BaseModel, extra="forbid"):
    """The LLM's full response for the extraction step."""

    actions: list[ExtractedAction]


# ---------------------------------------------------------------------------
# Decision outcome type
# ---------------------------------------------------------------------------

OutcomeType = Literal[
    "close_with_evidence",
    "carry_over",
    "mark_blocked",
    "ask_question",
    "draft_reminder",
    "new_action",
]


class Decision(BaseModel, extra="forbid"):
    """The LLM's decision for one existing action item."""

    action_id: str | None = None
    extracted_index: int | None = None
    outcome: OutcomeType
    evidence_line: int | None = None
    evidence_quote: str | None = None
    reason: str = Field(..., min_length=1)
    question: str | None = None

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> "Decision":
        """Enforce per-outcome required fields."""
        if self.outcome == "close_with_evidence":
            if self.evidence_line is None:
                raise ValueError("evidence_line is required for outcome 'close_with_evidence'")
            if not self.evidence_quote:
                raise ValueError("evidence_quote is required for outcome 'close_with_evidence'")
        if self.outcome == "ask_question":
            if not self.question:
                raise ValueError("question is required for outcome 'ask_question'")
        if self.outcome == "new_action":
            if self.extracted_index is None:
                raise ValueError("extracted_index is required for outcome 'new_action'")
        return self


class DecisionResult(BaseModel, extra="forbid"):
    """The LLM's full response for the decision step."""

    decisions: list[Decision]
