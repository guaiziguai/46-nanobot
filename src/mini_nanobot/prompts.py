from __future__ import annotations

from langchain_core.prompts import PromptTemplate

_MAIN = PromptTemplate.from_template(
    "你是 mini-nanobot，一个小巧的中文 AI agent。\n"
    "需要计算时调用 calculator；需要时间时调用 get_current_time。\n"
    "回答简洁，默认中文。\n"
)


def build_system_prompt() -> str:
    return _MAIN.format()