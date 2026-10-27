"""Tests for app.agent.schemas."""

import pytest
from app.agent.schemas import (
    Decision,
    DecisionResult,
    ExtractedAction,
    ExtractionResult,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# ExtractedAction
# ---------------------------------------------------------------------------


class TestExtractedAction:
    def test_happy_path(self) -> None:
        a = ExtractedAction(
            description="Write the report",
            owner="Alice",
            source_line=3,
            confidence=0.9,
            needs_clarification=False,
        )
        assert a.owner == "Alice"
        assert a.due_text is None

    def test_owner_none_requires_clarification(self) -> None:
        with pytest.raises(ValidationError, match="needs_clarification must be True"):
            ExtractedAction(
                description="Task",
                owner=None,
                source_line=1,
                confidence=0.5,
                needs_clarification=False,
            )

    def test_owner_none_requires_question(self) -> None:
        with pytest.raises(ValidationError, match="clarification_question"):
            ExtractedAction(
                description="Task",
                owner=None,
                source_line=1,
                confidence=0.5,
                needs_clarification=True,
                clarification_question=None,
            )

    def test_owner_none_with_question_valid(self) -> None:
        a = ExtractedAction(
            description="Task",
            owner=None,
            source_line=1,
            confidence=0.5,
            needs_clarification=True,
            clarification_question="Who is responsible?",
        )
        assert a.clarification_question == "Who is responsible?"

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="extra_inputs_not_permitted|Extra"):
            ExtractedAction(
                description="Task",
                owner="Bob",
                source_line=1,
                confidence=0.8,
                unexpected_field="boom",  # type: ignore[call-arg]
            )

    def test_confidence_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedAction(description="x", owner="A", source_line=1, confidence=1.5)

    def test_empty_description_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedAction(description="", owner="A", source_line=1, confidence=0.5)

    def test_source_line_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedAction(description="x", owner="A", source_line=0, confidence=0.5)


class TestExtractionResult:
    def test_empty_list_valid(self) -> None:
        r = ExtractionResult(actions=[])
        assert r.actions == []

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractionResult(actions=[], extra="no")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class TestDecision:
    def _base(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "outcome": "carry_over",
            "reason": "Still in progress",
        }
        base.update(overrides)
        return base

    def test_carry_over_happy_path(self) -> None:
        d = Decision(**self._base())  # type: ignore[arg-type]
        assert d.outcome == "carry_over"

    def test_close_with_evidence_requires_line_and_quote(self) -> None:
        with pytest.raises(ValidationError, match="evidence_line"):
            Decision(**self._base(outcome="close_with_evidence"))  # type: ignore[arg-type]

    def test_close_with_evidence_missing_quote(self) -> None:
        with pytest.raises(ValidationError, match="evidence_quote"):
            Decision(
                **self._base(outcome="close_with_evidence", evidence_line=5)  # type: ignore[arg-type]
            )

    def test_close_with_evidence_valid(self) -> None:
        d = Decision(
            **self._base(  # type: ignore[arg-type]
                outcome="close_with_evidence",
                evidence_line=5,
                evidence_quote="Done",
            )
        )
        assert d.evidence_line == 5

    def test_ask_question_requires_question(self) -> None:
        with pytest.raises(ValidationError, match="question is required"):
            Decision(**self._base(outcome="ask_question"))  # type: ignore[arg-type]

    def test_ask_question_valid(self) -> None:
        d = Decision(**self._base(outcome="ask_question", question="Who owns this?"))  # type: ignore[arg-type]
        assert d.question == "Who owns this?"

    def test_new_action_requires_extracted_index(self) -> None:
        with pytest.raises(ValidationError, match="extracted_index"):
            Decision(**self._base(outcome="new_action"))  # type: ignore[arg-type]

    def test_new_action_valid(self) -> None:
        d = Decision(**self._base(outcome="new_action", extracted_index=0))  # type: ignore[arg-type]
        assert d.extracted_index == 0

    def test_bad_outcome_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Decision(**self._base(outcome="do_nothing"))  # type: ignore[arg-type]

    def test_empty_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Decision(outcome="carry_over", reason="")

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Decision(outcome="carry_over", reason="ok", unknown="x")  # type: ignore[call-arg]


class TestDecisionResult:
    def test_valid(self) -> None:
        r = DecisionResult(decisions=[])
        assert r.decisions == []
