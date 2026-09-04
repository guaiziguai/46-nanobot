"""Dream：使用受限 agent 巩固长期记忆。"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from ..prompts import build_dream_prompt
from .store import MEMORY_FILES, MemoryBackend, MemorySnapshot, MemoryStore

MemoryLike = MemoryBackend | MemoryStore


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await _resolve(method(*args, **kwargs))


def _final_text(result: dict[str, Any]) -> str:
    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage) and message.content:
            return str(message.content)
    return ""


async def run_dream(llm: BaseChatModel, memory: MemoryLike) -> str:
    """运行一次隔离的 Dream；返回基于实际文件变化的结果说明。"""
    history = await _call(memory.read_history)
    cursor = await _call(memory.get_dream_cursor)
    new_entries = history[cursor:]

    if not new_entries:
        return "没有新的历史记录需要处理，跳过本次 Dream。"

    current_files = await _call(memory.read_all_memory_files)
    entries_text = "\n".join(f"- ({e['ts']}) {e['content']}" for e in new_entries)
    system_prompt = build_dream_prompt(current_files, entries_text, len(new_entries))
    snapshot: MemorySnapshot = await _call(memory.snapshot)

    @tool("read_memory_file")
    async def read_memory_file(name: str) -> str:
        """读取 SOUL.md、USER.md 或 MEMORY.md 的最新完整内容。"""
        return await _call(memory.read_memory_file, name)

    @tool("write_memory_file")
    async def write_memory_file(name: str, content: str) -> str:
        """原子改写一份记忆文件；name 只能是三种受支持的文件名。"""
        if name not in MEMORY_FILES:
            return f"拒绝写入不受支持的文件：{name}"
        await _call(memory.write_memory_file, name, content)
        return f"已写入 {name}"

    agent = create_agent(
        llm,
        tools=[read_memory_file, write_memory_file],
        system_prompt=system_prompt,
        middleware=[
            ModelCallLimitMiddleware(run_limit=6),
            ToolCallLimitMiddleware(run_limit=9),
        ],
        name="dream_agent",
    )

    try:
        result = await agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "请审阅新增摘要并按规则更新记忆。只在确有长期价值时写文件；"
                            "完成后用中文简述实际修改。"
                        )
                    )
                ]
            }
        )
    except BaseException:
        await _call(memory.restore, snapshot)
        raise

    changed = await _call(memory.has_changes, snapshot)
    if not changed:
        return "Dream 已完成，但没有产生长期记忆变化；游标未推进。"

    await _call(memory.set_dream_cursor, len(history))
    detail = _final_text(result).strip()
    return f"已更新长期记忆并推进游标。{f' {detail}' if detail else ''}"