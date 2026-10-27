"""LLM adapter layer.

Provides a single abstract interface LLMClient with four implementations:
- OllamaLLM   -- Local Ollama via HTTP API (/api/chat)
- GeminiLLM   -- Google Gemini via the google-genai SDK (>=2.x)
- GroqLLM     -- Groq via the groq SDK (>=0.13)
- FakeLLM     -- Canned responses for tests; goes through the real parse/validate path

Public entry point:
    get_llm(settings) -> LLMClient

Every call logs an llm_call event. Prompts and responses are never logged.
"""

import copy
import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.logging_setup import log_event

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base exception for all LLM failures."""


class LLMCallError(LLMError):
    """Network, timeout, or provider-side error calling the LLM."""


class LLMValidationError(LLMError):
    """LLM output could not be parsed and validated after all retries."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LLMClient(ABC):
    """Abstract LLM client.

    Subclasses implement _complete(); the public generate_structured() handles
    JSON parsing, pydantic validation, and the single-retry policy.
    """

    _provider: str = "unknown"
    _model: str = "unknown"

    def generate_structured(
        self,
        system: str,
        user: str,
        schema: type[T],
        *,
        call_name: str,
    ) -> T:
        """Call the LLM and return a validated pydantic model.

        Retry policy:
        - On invalid JSON or schema validation failure: retry ONCE with a message
          that includes the error and asks for corrected JSON only.
        - On provider / network failure (timeouts, 5xx): retry ONCE with a short
          backoff, then raise LLMCallError.
        - After retries are exhausted, raise LLMValidationError or LLMCallError.
        """
        user_hash = hashlib.sha256(user.encode()).hexdigest()[:16]
        user_len = len(user)
        schema_json = schema.model_json_schema()
        last_error: Exception | None = None

        for attempt in range(1, 3):  # attempt 1 then 2
            t0 = time.monotonic()
            success = False
            try:
                user_msg = user if attempt == 1 else _retry_prompt(user, last_error)
                raw = self._complete(system, user_msg, schema_json)
                parsed = self._parse_and_validate(raw, schema)
                success = True
                latency_ms = int((time.monotonic() - t0) * 1000)
                self._log_call(call_name, attempt, latency_ms, success, user_hash, user_len)
                return parsed
            except (LLMValidationError, json.JSONDecodeError, ValidationError) as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                self._log_call(call_name, attempt, latency_ms, success, user_hash, user_len)
                last_error = exc
                # One retry for parse/validate failures.
                if attempt == 2:
                    raise LLMValidationError(
                        f"LLM output failed validation after {attempt} attempts "
                        f"for call '{call_name}': {exc}"
                    ) from exc
            except LLMCallError as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                self._log_call(call_name, attempt, latency_ms, success, user_hash, user_len)
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(1)  # short backoff before retry

        # Unreachable, but satisfies the type checker.
        raise LLMCallError("generate_structured exhausted retries unexpectedly")

    @abstractmethod
    def _complete(self, system: str, user: str, schema_json: dict[str, Any]) -> str:
        """Call the provider and return the raw text response."""

    @classmethod
    def _extract_json_text(cls, raw: str) -> str:
        """Strip markdown fences, thinking tags, and extract outermost JSON object/array."""
        text = raw.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if "```" in text:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1).strip()
        if not (text.startswith("{") or text.startswith("[")):
            fb = text.find("{")
            fk = text.find("[")
            start = -1
            if fb != -1 and fk != -1:
                start = min(fb, fk)
            elif fb != -1:
                start = fb
            elif fk != -1:
                start = fk

            if start != -1:
                lb = text.rfind("}")
                lk = text.rfind("]")
                end = max(lb, lk)
                if end > start:
                    text = text[start : end + 1].strip()
        return text

    @classmethod
    def _clean_data_for_schema(cls, data: Any, schema: type[T]) -> Any:
        """Sanitize data for known schemas to handle small LLM quirks robustly."""
        if isinstance(data, list):
            fields = getattr(schema, "model_fields", {})
            if "actions" in fields:
                data = {"actions": data}
            elif "decisions" in fields:
                data = {"decisions": data}

        if isinstance(data, dict):
            if isinstance(data.get("actions"), list):
                allowed_action_keys = {
                    "description",
                    "owner",
                    "due_text",
                    "source_line",
                    "confidence",
                    "needs_clarification",
                    "clarification_question",
                }
                for item in data["actions"]:
                    if isinstance(item, dict):
                        # Clean confidence
                        conf = item.get("confidence")
                        if conf is None:
                            item["confidence"] = 0.8
                        else:
                            try:
                                conf_f = float(conf)
                                if conf_f > 1.0:
                                    conf_f = conf_f / 100.0 if conf_f <= 100.0 else 1.0
                                elif conf_f < 0.0:
                                    conf_f = 0.0
                                item["confidence"] = conf_f
                            except (ValueError, TypeError):
                                item["confidence"] = 0.8

                        # Clean source_line
                        src = item.get("source_line")
                        if src is None:
                            item["source_line"] = 1
                        else:
                            try:
                                item["source_line"] = max(1, int(src))
                            except (ValueError, TypeError):
                                item["source_line"] = 1

                        # Clean owner and clarification
                        owner = item.get("owner")
                        if not owner or str(owner).strip().lower() in ("none", "null", ""):
                            item["owner"] = None
                            item["needs_clarification"] = True
                            if not item.get("clarification_question"):
                                item["clarification_question"] = (
                                    "No owner specified. Who is responsible?"
                                )

                        # Remove extra keys
                        for k in list(item.keys()):
                            if k not in allowed_action_keys:
                                del item[k]

                # Root extra keys
                for k in list(data.keys()):
                    if k not in {"actions"}:
                        del data[k]

            elif isinstance(data.get("decisions"), list):
                allowed_decision_keys = {
                    "action_id",
                    "extracted_index",
                    "outcome",
                    "evidence_line",
                    "evidence_quote",
                    "reason",
                    "question",
                }
                for item in data["decisions"]:
                    if isinstance(item, dict):
                        if not item.get("reason"):
                            item["reason"] = "Decision inferred from notes"
                        if item.get("outcome") == "ask_question" and not item.get("question"):
                            item["question"] = (
                                item.get("reason") or "Evidence for this action could not be verified."
                            )
                        for k in list(item.keys()):
                            if k not in allowed_decision_keys:
                                del item[k]
                for k in list(data.keys()):
                    if k not in {"decisions"}:
                        del data[k]

        return data

    @classmethod
    def _parse_and_validate(cls, raw: str, schema: type[T]) -> T:
        """Parse JSON and validate against the pydantic schema."""
        clean_text = cls._extract_json_text(raw)
        try:
            data = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(
                f"LLM returned invalid JSON: {exc.msg}", exc.doc, exc.pos
            ) from exc
        data = cls._clean_data_for_schema(data, schema)
        return schema.model_validate(data)

    def _log_call(
        self,
        call_name: str,
        attempt: int,
        latency_ms: int,
        success: bool,
        user_hash: str,
        user_len: int,
    ) -> None:
        try:
            log_event(
                "llm_call",
                {
                    "call_name": call_name,
                    "provider": self._provider,
                    "model": self._model,
                    "attempt": attempt,
                    "latency_ms": latency_ms,
                    "success": success,
                    "user_prompt_sha256_prefix": user_hash,
                    "user_prompt_len": user_len,
                },
            )
        except Exception:  # noqa: BLE001
            pass  # Logging must never crash the caller.


def _retry_prompt(original_user: str, error: Exception | None) -> str:
    """Build the retry user message that includes the validation error."""
    error_msg = str(error) if error else "unknown error"
    return (
        f"{original_user}\n\n"
        f"Your previous response could not be parsed. Error: {error_msg}\n"
        "Please respond with ONLY valid JSON that matches the required schema. "
        "No explanation, no markdown fences."
    )


# ---------------------------------------------------------------------------
# OllamaLLM
# ---------------------------------------------------------------------------


class OllamaLLM(LLMClient):
    """LLM client backed by local Ollama (via HTTP API /api/chat)."""

    _provider = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = float(timeout_seconds)

    def _prepare_schema(self, schema_json: dict[str, Any]) -> dict[str, Any]:
        """Make all properties required in the schema for Ollama's grammar-constrained decoding."""
        schema = copy.deepcopy(schema_json)
        defs = schema.get("$defs") or schema.get("definitions") or {}
        for definition in defs.values():
            if isinstance(definition, dict) and "properties" in definition:
                definition["required"] = list(definition["properties"].keys())
        if "properties" in schema:
            schema["required"] = list(schema["properties"].keys())
        return schema

    def _complete(self, system: str, user: str, schema_json: dict[str, Any]) -> str:
        import httpx

        url = f"{self._base_url}/api/chat"
        schema = self._prepare_schema(schema_json)
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.0},
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload)
                if response.status_code == 400:
                    # Fallback to general JSON format if schema is not supported by Ollama version
                    payload["format"] = "json"
                    response = client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise LLMCallError(
                f"Cannot connect to Ollama server at {self._base_url}. "
                "Please ensure Ollama is installed and running (e.g. run 'ollama serve')."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMCallError(
                f"Ollama request to {self._base_url} timed out after {self._timeout:.0f}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMCallError(f"Ollama HTTP error: {exc}") from exc

        if response.status_code == 404:
            raise LLMCallError(
                f"Ollama model '{self._model}' not found at {self._base_url}. "
                f"Please ensure the model is pulled using 'ollama pull {self._model}'."
            )
        if response.status_code != 200:
            raise LLMCallError(
                f"Ollama server returned error status {response.status_code}: {response.text}"
            )

        try:
            res_json = response.json()
        except Exception as exc:
            raise LLMCallError(f"Ollama returned invalid JSON envelope: {exc}") from exc

        content = res_json.get("message", {}).get("content")
        if not content or not content.strip():
            raise LLMCallError(f"Ollama model '{self._model}' returned an empty response")

        return content


# ---------------------------------------------------------------------------
# GeminiLLM
# ---------------------------------------------------------------------------


class GeminiLLM(LLMClient):
    """LLM client backed by Google Gemini (google-genai SDK >= 2.x)."""

    _provider = "gemini"

    def __init__(self, api_key: str, model: str, timeout_seconds: int) -> None:
        import google.genai as genai
        from google.genai import types as gtypes

        self._model = model
        self._timeout = timeout_seconds
        self._gtypes = gtypes
        self._client = genai.Client(
            api_key=api_key,
            http_options=gtypes.HttpOptions(timeout=timeout_seconds * 1000),
        )

    def _complete(self, system: str, user: str, schema_json: dict[str, Any]) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user,
                config=self._gtypes.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
            text = response.text
            if text is None:
                raise LLMCallError("Gemini returned an empty response")
            return text
        except LLMCallError:
            raise
        except Exception as exc:
            raise LLMCallError(f"Gemini API error: {exc}") from exc


# ---------------------------------------------------------------------------
# GroqLLM
# ---------------------------------------------------------------------------


class GroqLLM(LLMClient):
    """LLM client backed by Groq (groq SDK >= 0.13)."""

    _provider = "groq"

    def __init__(self, api_key: str, model: str, timeout_seconds: int) -> None:
        import groq as groq_sdk

        self._model = model
        self._client = groq_sdk.Groq(api_key=api_key, timeout=float(timeout_seconds))

    def _complete(self, system: str, user: str, schema_json: dict[str, Any]) -> str:
        """Groq JSON mode requires the schema in the system prompt."""
        schema_hint = json.dumps(schema_json, indent=2)
        full_system = (
            f"{system}\n\n"
            f"You MUST respond with a single valid JSON object that strictly follows "
            f"this JSON schema:\n{schema_hint}\n"
            "Respond with ONLY the JSON object, no extra text."
        )
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = completion.choices[0].message.content
            if content is None:
                raise LLMCallError("Groq returned an empty response")
            return content
        except LLMCallError:
            raise
        except Exception as exc:
            raise LLMCallError(f"Groq API error: {exc}") from exc


# ---------------------------------------------------------------------------
# FakeLLM
# ---------------------------------------------------------------------------


class FakeLLM(LLMClient):
    """Canned-response LLM for tests.

    Responses are consumed in order. Each entry can be:
    - dict        -- serialised to JSON and returned
    - str         -- returned as-is (may be invalid JSON to test retry)
    - Exception   -- raised to simulate a provider failure

    Goes through the real parse, validate and retry path in generate_structured()
    so retry behaviour is fully testable.
    """

    _provider = "fake"
    _model = "fake"

    def __init__(self, responses: list[dict[str, Any] | str | Exception]) -> None:
        self._queue: list[dict[str, Any] | str | Exception] = list(responses)
        self.calls: list[dict[str, str]] = []

    def generate_structured(
        self,
        system: str,
        user: str,
        schema: type[T],
        *,
        call_name: str,
    ) -> T:
        """Record call metadata before delegating to the base implementation."""
        self.calls.append({"call_name": call_name, "system": system, "user": user})
        return super().generate_structured(system, user, schema, call_name=call_name)

    def _complete(self, system: str, user: str, schema_json: dict[str, Any]) -> str:
        if not self._queue:
            raise LLMCallError(
                "FakeLLM has no more canned responses. " "Add more entries to the responses list."
            )
        response = self._queue.pop(0)
        if isinstance(response, Exception):
            raise LLMCallError(str(response)) from response
        if isinstance(response, dict):
            return json.dumps(response)
        return response  # str -- may be invalid JSON


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_llm(settings: Any) -> LLMClient:
    """Construct and return the appropriate LLMClient for the given settings."""
    provider = settings.llm_provider
    if provider == "ollama":
        return OllamaLLM(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if provider == "gemini":
        return GeminiLLM(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if provider == "groq":
        return GroqLLM(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if provider == "fake":
        return FakeLLM(responses=[])
    raise ValueError(f"Unknown provider {provider!r}")
