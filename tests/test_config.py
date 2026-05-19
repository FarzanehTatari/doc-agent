"""Smoke tests for the config module — no API key required."""

import pytest

from doc_agent.config import Settings


def test_defaults_when_env_empty(monkeypatch):
    """With no environment variables, defaults take over."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    s = Settings(_env_file=None)
    assert s.ai_model == "claude-opus-4-7"
    assert s.log_level == "INFO"
    assert s.has_api_key is False


def test_api_key_picked_up_from_env(monkeypatch):
    """Setting ANTHROPIC_API_KEY in the env populates the Settings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-1234567890")
    s = Settings(_env_file=None)
    assert s.has_api_key is True
    assert s.anthropic_api_key == "sk-test-1234567890"


def test_log_level_validates(monkeypatch):
    """Invalid log levels should raise."""
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(Exception):  # pydantic ValidationError, but keep import-light
        Settings(_env_file=None)
