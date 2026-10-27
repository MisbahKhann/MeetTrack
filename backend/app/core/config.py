"""Application configuration.

Settings are loaded from environment variables (via a .env file if present).
Use get_settings() everywhere -- it is cached and returns the same instance
across calls. Call clear_settings_cache() in tests to force a fresh load.
"""

import functools
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_VALID_PROVIDERS = frozenset({"ollama", "gemini", "groq", "fake"})
_ENV_FILE = Path(__file__).parent.parent.parent.parent / ".env"


@dataclass(frozen=True)
class Settings:
    """Typed, immutable application settings.

    API keys are never shown in __repr__.
    """

    llm_provider: str = "ollama"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"
    db_path: str = "data/meettrack.db"
    log_path: str = "logs/meettrack.log.jsonl"
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 1
    environment: str = "dev"

    def __repr__(self) -> str:
        """Return a string representation that never exposes API keys."""
        masked_gemini = "***" if self.gemini_api_key else ""
        masked_groq = "***" if self.groq_api_key else ""
        return (
            f"Settings("
            f"llm_provider={self.llm_provider!r}, "
            f"ollama_base_url={self.ollama_base_url!r}, "
            f"ollama_model={self.ollama_model!r}, "
            f"gemini_model={self.gemini_model!r}, "
            f"groq_model={self.groq_model!r}, "
            f"db_path={self.db_path!r}, "
            f"log_path={self.log_path!r}, "
            f"llm_timeout_seconds={self.llm_timeout_seconds!r}, "
            f"llm_max_retries={self.llm_max_retries!r}, "
            f"environment={self.environment!r}, "
            f"gemini_api_key={masked_gemini!r}, "
            f"groq_api_key={masked_groq!r}"
            f")"
        )


def _validate(s: Settings) -> None:
    """Raise ValueError with a clear message if settings are invalid."""
    if s.llm_provider not in _VALID_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider {s.llm_provider!r}. "
            f"Must be one of: {sorted(_VALID_PROVIDERS)}"
        )
    if s.llm_provider == "gemini" and not s.gemini_api_key:
        raise ValueError(
            "GEMINI_API_KEY must be set when LLM_PROVIDER=gemini. "
            "Add it to your .env file or environment."
        )
    if s.llm_provider == "groq" and not s.groq_api_key:
        raise ValueError(
            "GROQ_API_KEY must be set when LLM_PROVIDER=groq. "
            "Add it to your .env file or environment."
        )
    if s.llm_provider == "ollama":
        if not s.ollama_base_url:
            raise ValueError(
                "OLLAMA_BASE_URL must be set when LLM_PROVIDER=ollama."
            )
        if not s.ollama_model:
            raise ValueError(
                "OLLAMA_MODEL must be set when LLM_PROVIDER=ollama."
            )


def load_settings() -> Settings:
    """Read environment variables (loading .env if present) and return Settings.

    Raises ValueError for invalid or incomplete configuration.
    """
    load_dotenv(dotenv_path=_ENV_FILE, override=False)

    def _int(key: str, default: int) -> int:
        raw = os.environ.get(key, "")
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    s = Settings(
        llm_provider=os.environ.get("LLM_PROVIDER", "ollama"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        groq_model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b"),
        db_path=os.environ.get("DB_PATH", "data/meettrack.db"),
        log_path=os.environ.get("LOG_PATH", "logs/meettrack.log.jsonl"),
        llm_timeout_seconds=_int("LLM_TIMEOUT_SECONDS", 120),
        llm_max_retries=_int("LLM_MAX_RETRIES", 1),
        environment=os.environ.get("ENVIRONMENT", "dev"),
    )
    _validate(s)
    return s


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton.

    Construct with: LLM_PROVIDER=fake for tests so no real API keys are needed.
    """
    return load_settings()


def clear_settings_cache() -> None:
    """Clear the lru_cache so the next get_settings() call re-reads the environment.

    Call this in test teardown when environment variables are patched.
    """
    get_settings.cache_clear()
