"""Tests for app.agent.llm -- no real network calls."""

from unittest.mock import MagicMock, patch

import pytest
from app.agent.llm import (
    FakeLLM,
    GeminiLLM,
    GroqLLM,
    LLMCallError,
    LLMValidationError,
)
from app.agent.schemas import ExtractionResult
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Minimal schema for generic tests
# ---------------------------------------------------------------------------


class _Echo(BaseModel, extra="forbid"):
    message: str


# ---------------------------------------------------------------------------
# FakeLLM tests
# ---------------------------------------------------------------------------


class TestFakeLLMHappyPath:
    def test_dict_response_returns_model(self) -> None:
        llm = FakeLLM([{"message": "hello"}])
        result = llm.generate_structured("sys", "user", _Echo, call_name="test")
        assert result.message == "hello"

    def test_call_recorded(self) -> None:
        llm = FakeLLM([{"message": "hi"}])
        llm.generate_structured("sys prompt", "user msg", _Echo, call_name="echo_test")
        assert len(llm.calls) == 1
        assert llm.calls[0]["call_name"] == "echo_test"
        assert llm.calls[0]["system"] == "sys prompt"
        assert llm.calls[0]["user"] == "user msg"

    def test_multiple_responses_consumed_in_order(self) -> None:
        llm = FakeLLM([{"message": "first"}, {"message": "second"}])
        r1 = llm.generate_structured("s", "u", _Echo, call_name="c1")
        r2 = llm.generate_structured("s", "u", _Echo, call_name="c2")
        assert r1.message == "first"
        assert r2.message == "second"

    def test_extraction_result_schema(self) -> None:
        payload = {
            "actions": [
                {
                    "description": "Write report",
                    "owner": "Alice",
                    "source_line": 3,
                    "confidence": 0.9,
                    "needs_clarification": False,
                }
            ]
        }
        llm = FakeLLM([payload])
        result = llm.generate_structured("s", "u", ExtractionResult, call_name="extract")
        assert result.actions[0].owner == "Alice"


class TestFakeLLMRetry:
    def test_invalid_json_then_valid_succeeds(self) -> None:
        """Bad JSON on attempt 1, valid JSON on attempt 2 -> success."""
        llm = FakeLLM(["not-json-{{", {"message": "ok"}])
        result = llm.generate_structured("s", "u", _Echo, call_name="retry_test")
        assert result.message == "ok"

    def test_invalid_json_twice_raises_validation_error(self) -> None:
        llm = FakeLLM(["bad{", "also bad{"])
        with pytest.raises(LLMValidationError):
            llm.generate_structured("s", "u", _Echo, call_name="fail_test")

    def test_schema_validation_failure_then_valid_succeeds(self) -> None:
        """Valid JSON but wrong schema on attempt 1, correct on attempt 2."""
        llm = FakeLLM([{"wrong_field": "x"}, {"message": "fixed"}])
        result = llm.generate_structured("s", "u", _Echo, call_name="schema_retry")
        assert result.message == "fixed"

    def test_schema_failure_twice_raises(self) -> None:
        llm = FakeLLM([{"bad": 1}, {"also_bad": 2}])
        with pytest.raises(LLMValidationError):
            llm.generate_structured("s", "u", _Echo, call_name="double_fail")


class TestFakeLLMCallError:
    def test_exception_response_raises_llm_call_error(self) -> None:
        # Two Exception entries: one per retry attempt (attempt 1 and attempt 2).
        llm = FakeLLM([RuntimeError("provider down"), RuntimeError("provider down again")])
        with pytest.raises(LLMCallError, match="provider down"):
            llm.generate_structured("s", "u", _Echo, call_name="err_test")

    def test_runs_out_of_responses_raises(self) -> None:
        llm = FakeLLM([])
        with pytest.raises(LLMCallError, match="no more canned responses"):
            llm.generate_structured("s", "u", _Echo, call_name="empty")


# ---------------------------------------------------------------------------
# GeminiLLM -- mock the private _complete method only
# ---------------------------------------------------------------------------


class TestGeminiLLMMocked:
    def test_calls_complete_and_returns_model(self) -> None:
        llm = GeminiLLM.__new__(GeminiLLM)
        llm._model = "gemini-test"
        with patch.object(llm, "_complete", return_value='{"message": "from gemini"}'):
            result = llm.generate_structured("s", "u", _Echo, call_name="gemini_test")
        assert result.message == "from gemini"

    def test_provider_error_raises_llm_call_error(self) -> None:
        llm = GeminiLLM.__new__(GeminiLLM)
        llm._model = "gemini-test"
        with patch.object(llm, "_complete", side_effect=LLMCallError("timeout")):
            with pytest.raises(LLMCallError, match="timeout"):
                llm.generate_structured("s", "u", _Echo, call_name="gemini_err")


class TestGeminiLLMComplete:
    """Test the _complete method by mocking the SDK client."""

    def _make(self) -> GeminiLLM:
        llm = GeminiLLM.__new__(GeminiLLM)
        llm._model = "gemini-2.0-flash"
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"message": "hi"}'
        mock_client.models.generate_content.return_value = mock_response
        llm._client = mock_client
        llm._gtypes = MagicMock()
        return llm

    def test_returns_text_from_sdk(self) -> None:
        llm = self._make()
        raw = llm._complete("sys", "user", {})
        assert raw == '{"message": "hi"}'

    def test_none_response_raises(self) -> None:
        llm = self._make()
        llm._client.models.generate_content.return_value.text = None
        with pytest.raises(LLMCallError, match="empty response"):
            llm._complete("sys", "user", {})

    def test_sdk_exception_raises_llm_call_error(self) -> None:
        llm = self._make()
        llm._client.models.generate_content.side_effect = Exception("network error")
        with pytest.raises(LLMCallError, match="Gemini API error"):
            llm._complete("sys", "user", {})


# ---------------------------------------------------------------------------
# GroqLLM -- mock the SDK client
# ---------------------------------------------------------------------------


class TestGroqLLMMocked:
    def test_calls_complete_and_returns_model(self) -> None:
        llm = GroqLLM.__new__(GroqLLM)
        llm._model = "groq-test"
        with patch.object(llm, "_complete", return_value='{"message": "from groq"}'):
            result = llm.generate_structured("s", "u", _Echo, call_name="groq_test")
        assert result.message == "from groq"


class TestGroqLLMComplete:
    def _make(self) -> GroqLLM:
        llm = GroqLLM.__new__(GroqLLM)
        llm._model = "groq-model"
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '{"message": "groq_response"}'
        mock_client.chat.completions.create.return_value.choices = [mock_choice]
        llm._client = mock_client
        return llm

    def test_returns_text_from_sdk(self) -> None:
        llm = self._make()
        raw = llm._complete("sys", "user", {})
        assert raw == '{"message": "groq_response"}'

    def test_none_content_raises(self) -> None:
        llm = self._make()
        llm._client.chat.completions.create.return_value.choices[0].message.content = None
        with pytest.raises(LLMCallError, match="empty response"):
            llm._complete("sys", "user", {})

    def test_sdk_exception_raises_llm_call_error(self) -> None:
        llm = self._make()
        llm._client.chat.completions.create.side_effect = Exception("rate limit")
        with pytest.raises(LLMCallError, match="Groq API error"):
            llm._complete("sys", "user", {})

    def test_schema_included_in_system_prompt(self) -> None:
        llm = self._make()
        schema = {"type": "object", "properties": {"message": {"type": "string"}}}
        llm._complete("my system", "user msg", schema)
        call_args = llm._client.chat.completions.create.call_args
        system_content = call_args.kwargs["messages"][0]["content"]
        assert "my system" in system_content
        assert '"type": "object"' in system_content
