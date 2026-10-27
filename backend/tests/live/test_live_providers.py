"""Optional live provider smoke tests.

These tests make real API calls and are EXCLUDED from CI.
Run them locally only when API keys are present:

    pytest backend/tests/live/ -v -m live

They are automatically skipped when the required environment variable is absent.
"""

import os

import pytest
from app.agent.llm import GeminiLLM, GroqLLM
from app.agent.schemas import ExtractionResult

_NOTE = """
Line 1: Alice will update the design document by Friday.
Line 2: Bob is responsible for reviewing the pull request this week.
Line 3: The team agreed to meet again next Monday.
"""

_SYSTEM = (
    "Extract action items from the meeting notes. "
    "Return valid JSON matching the ExtractionResult schema."
)


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set -- skipping live Gemini test",
)
def test_gemini_extracts_actions() -> None:
    """Live smoke test: Gemini returns a parseable ExtractionResult."""
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    llm = GeminiLLM(api_key=key, model=model, timeout_seconds=30)
    result = llm.generate_structured(_SYSTEM, _NOTE, ExtractionResult, call_name="live_extract")
    assert isinstance(result, ExtractionResult)
    assert len(result.actions) >= 1


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set -- skipping live Groq test",
)
def test_groq_extracts_actions() -> None:
    """Live smoke test: Groq returns a parseable ExtractionResult."""
    key = os.environ["GROQ_API_KEY"]
    model = os.environ.get("GROQ_MODEL", "llama3-8b-8192")
    llm = GroqLLM(api_key=key, model=model, timeout_seconds=30)
    result = llm.generate_structured(_SYSTEM, _NOTE, ExtractionResult, call_name="live_extract")
    assert isinstance(result, ExtractionResult)
    assert len(result.actions) >= 1
