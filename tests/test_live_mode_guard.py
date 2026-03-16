import os

import pytest

from staff.providers.openai_adapter import OpenAIAdapter
from staff.providers.anthropic_adapter import AnthropicAdapter


def test_openai_adapter_disabled_without_live_mode(monkeypatch):
    monkeypatch.setenv("STAFF_LIVE_MODE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        OpenAIAdapter()


def test_anthropic_adapter_disabled_without_live_mode(monkeypatch):
    monkeypatch.setenv("STAFF_LIVE_MODE", "0")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        AnthropicAdapter()
