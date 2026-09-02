from __future__ import annotations

from unittest.mock import MagicMock, patch

from mini_nanobot.config import AppConfig, ProviderConfig
from mini_nanobot.graph import build_agent
from mini_nanobot.prompts import build_system_prompt
from mini_nanobot.tools.basic import BASIC_TOOLS


def _make_cfg() -> AppConfig:
    return AppConfig(
        provider=ProviderConfig(
            api_key="sk-test",
            api_base="https://api.example.com/v1",
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=1024,
            timeout_seconds=30,
        )
    )


def test_build_agent_wires_llm_tools_and_prompt() -> None:
    cfg = _make_cfg()
    fake_llm = object()
    fake_agent = MagicMock(name="agent")
    captured: dict = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return fake_agent

    with (
        patch("mini_nanobot.graph.ChatOpenAI", return_value=fake_llm) as mock_llm,
        patch("mini_nanobot.graph.create_agent", side_effect=fake_create_agent),
    ):
        agent = build_agent(cfg)

    mock_llm.assert_called_once_with(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-4o-mini",
        temperature=0.3,
        max_tokens=1024,
        timeout=30,
    )
    assert agent is fake_agent
    assert captured["llm"] is fake_llm
    assert captured["tools"] == BASIC_TOOLS
    assert captured["system_prompt"] == build_system_prompt()
    assert captured["name"] == "mini-nanobot"

