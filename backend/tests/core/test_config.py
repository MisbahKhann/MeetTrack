"""Tests for app.core.config."""

import os
from unittest.mock import patch

import pytest
from app.core.config import Settings, clear_settings_cache, get_settings, load_settings


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Ensure each test starts with a fresh settings cache."""
    clear_settings_cache()
    yield
    clear_settings_cache()


def _env(**overrides: str) -> dict[str, str]:
    """Minimal env dict with fake provider (no key needed) plus any overrides."""
    base = {
        "LLM_PROVIDER": "fake",
        "GEMINI_API_KEY": "",
        "GROQ_API_KEY": "",
    }
    base.update(overrides)
    return base


class TestDefaults:
    def test_fake_provider_needs_no_key(self) -> None:
        with patch.dict(os.environ, _env(), clear=True):
            s = load_settings()
        assert s.llm_provider == "fake"

    def test_defaults_applied(self) -> None:
        with patch.dict(os.environ, _env(), clear=True):
            s = load_settings()
        assert s.gemini_model == "gemini-2.0-flash"
        assert s.llm_timeout_seconds == 30
        assert s.llm_max_retries == 1
        assert s.environment == "dev"

    def test_custom_values(self) -> None:
        with patch.dict(
            os.environ,
            _env(LLM_TIMEOUT_SECONDS="60", LLM_MAX_RETRIES="2", ENVIRONMENT="test"),
            clear=True,
        ):
            s = load_settings()
        assert s.llm_timeout_seconds == 60
        assert s.llm_max_retries == 2
        assert s.environment == "test"


class TestValidation:
    def test_unknown_provider_raises(self) -> None:
        with patch.dict(os.environ, _env(LLM_PROVIDER="openai"), clear=True):
            with pytest.raises(ValueError, match="Unknown LLM provider"):
                load_settings()

    def test_gemini_missing_key_raises(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": ""}, clear=True):
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                load_settings()

    def test_groq_missing_key_raises(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "groq", "GROQ_API_KEY": ""}, clear=True):
            with pytest.raises(ValueError, match="GROQ_API_KEY"):
                load_settings()

    def test_gemini_with_key_succeeds(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "sk-test"},
            clear=True,
        ):
            s = load_settings()
        assert s.llm_provider == "gemini"


class TestRepr:
    def test_repr_masks_gemini_key(self) -> None:
        s = Settings(
            llm_provider="fake",
            gemini_api_key="super-secret-key",
            groq_api_key="",
        )
        r = repr(s)
        assert "super-secret-key" not in r
        assert "***" in r

    def test_repr_masks_groq_key(self) -> None:
        s = Settings(
            llm_provider="fake",
            gemini_api_key="",
            groq_api_key="another-secret",
        )
        r = repr(s)
        assert "another-secret" not in r
        assert "***" in r

    def test_repr_empty_keys_not_starred(self) -> None:
        s = Settings(llm_provider="fake", gemini_api_key="", groq_api_key="")
        r = repr(s)
        # Empty key should show as empty string, not "***"
        assert "gemini_api_key=''" in r or 'gemini_api_key=""' in r


class TestCache:
    def test_get_settings_cached(self) -> None:
        with patch.dict(os.environ, _env(), clear=True):
            a = get_settings()
            b = get_settings()
        assert a is b

    def test_clear_cache_forces_reload(self) -> None:
        with patch.dict(os.environ, _env(), clear=True):
            a = get_settings()
        clear_settings_cache()
        with patch.dict(os.environ, _env(ENVIRONMENT="test"), clear=True):
            b = get_settings()
        assert a is not b
        assert b.environment == "test"
