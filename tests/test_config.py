from __future__ import annotations

import pytest
from pydantic import ValidationError

from mini_nanobot.config import ProviderConfig


def test_rejects_workspace_placeholder() -> None:
    with pytest.raises(ValidationError, match="占位符"):
        ProviderConfig(
            api_key="sk-test",
            api_base="https://[workspace-id].example.com/v1",
        )


def test_strips_trailing_slash() -> None:
    cfg = ProviderConfig(
        api_key="sk-test",
        api_base="https://api.example.com/v1/",
    )
    assert cfg.api_base == "https://api.example.com/v1"


def test_env_default_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "OPENAI_API_BASE",
        "https://[workspace-id].example.com/v1",
    )
    with pytest.raises(ValidationError, match="占位符"):
        ProviderConfig()