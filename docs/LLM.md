# LLM Adapter

## Provider selection

The active provider is set by the `LLM_PROVIDER` environment variable:

| Value | Class | Required settings / keys |
|-------|-------|--------------------------|
| `ollama` (default) | `OllamaLLM` | `OLLAMA_BASE_URL` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `qwen2.5:1.5b`) |
| `gemini` | `GeminiLLM` | `GEMINI_API_KEY` |
| `groq` | `GroqLLM` | `GROQ_API_KEY` |
| `fake` | `FakeLLM` | none |

`load_settings()` raises a `ValueError` at startup if a cloud provider is
selected without its required API key. The Ollama provider runs locally without cloud API keys.
The fake provider is always available for tests with no keys.

## Using FakeLLM in tests

```python
from app.agent.llm import FakeLLM
from app.agent.schemas import ExtractionResult

llm = FakeLLM(responses=[
    {
        "actions": [
            {
                "description": "Write the report",
                "owner": "Alice",
                "source_line": 3,
                "confidence": 0.9,
                "needs_clarification": False,
            }
        ]
    }
])
result = llm.generate_structured(
    system="Extract actions",
    user="Meeting notes...",
    schema=ExtractionResult,
    call_name="extract",
)
```

Responses are consumed in order. Each entry can be:
- `dict` -- serialised to JSON and returned
- `str` -- returned as-is (useful for testing invalid-JSON retry behaviour)
- `Exception` instance -- raised to simulate a provider failure

FakeLLM records every call in `llm.calls` so tests can assert on what was sent.
It goes through the same parse, validate and retry path as real providers, so
retry behaviour is fully testable without a network.

## Retry rules

All retry logic lives in `LLMClient.generate_structured()`. Subclasses only
implement `_complete()`.

| Failure | Action |
|---------|--------|
| Invalid JSON from provider | Retry once with the error embedded in the user message |
| Pydantic validation failure | Retry once with the error embedded in the user message |
| Provider / network error (5xx, timeout) | Retry once after a 1-second backoff |
| Second consecutive failure (any type) | Raise `LLMValidationError` or `LLMCallError` |

The retry user message includes the exact validation error text and asks for
corrected JSON only (no markdown fences, no explanation).

## What is logged

Every call to `generate_structured()` logs one or two `llm_call` events (one per
attempt) via `log_event()`. Each event contains:

| Field | Value |
|-------|-------|
| `call_name` | Caller-supplied name, e.g. `"extract"` |
| `provider` | `"ollama"`, `"gemini"`, `"groq"`, or `"fake"` |
| `model` | Model name string |
| `attempt` | 1 or 2 |
| `latency_ms` | Wall-clock time for that attempt |
| `success` | `true` or `false` |
| `user_prompt_sha256_prefix` | First 16 hex chars of SHA-256 of the user prompt |
| `user_prompt_len` | Character count of the user prompt |

## What is never logged

- The full system prompt
- The full user prompt
- The full LLM response body
- Any API key, token or secret
- Any personally identifiable information from meeting notes

Meeting notes may contain sensitive information; only their length and a
non-reversible hash prefix are recorded to support debugging without exposure.

## Running live tests

Live tests are in `backend/tests/live/` and are excluded from normal `pytest` and
CI runs. To run them locally with a real key:

```powershell
# Gemini
$env:GEMINI_API_KEY = "your-key"
pytest backend/tests/live/ -v -m live

# Groq
$env:GROQ_API_KEY = "your-key"
pytest backend/tests/live/ -v -m live
```

CI never runs these tests. No key is needed for the normal test suite.
