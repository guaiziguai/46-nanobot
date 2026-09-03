"""LangChain `create_agent` 的中间件组装。

标准能力（模型/工具重试、调用预算、摘要）直接使用 LangChain
内置 middleware。本章只保留两件项目特有的事：

1. 每次模型调用前动态注入本地长期记忆与 Goal；
2. 把 `SummarizationMiddleware` 产生的摘要归档给 Dream。
"""

from __future__ import annotations

import hashlib
import inspect
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
    dynamic_prompt,
    hook_config,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from .prompts import build_system_prompt
from .retry import classify_error
from .state import AgentContext, AgentState

@dynamic_prompt
async def runtime_prompt(request: ModelRequest) -> str:
    context: AgentContext = request.runtime.context
    memory_files = context.memory.read_all_memory_files()
    if inspect.isawaitable(memory_files):
        memory_files = await memory_files
    return build_system_prompt(
        memory_files,
        request.state.get("goal_state"),
    )

class SummaryArchiveMiddleware(AgentMiddleware[AgentState, AgentContext]):
    """把 `SummarizationMiddleware` 产生的摘要归档给 Dream。
    "把 LangChain 摘要消息追加到 Dream 的 history.jsonl，内容哈希用于去重。
    """
    state_schema = AgentState

    async def abefore_model(
        self,
        state: AgentState,
        runtime,
    ) -> dict[str, Any] | None:
        summaries = [
            message
            for message in state["messages"]
            if isinstance(message, HumanMessage)
            and message.additional_kwargs.get("lc_source") == "summarization"
        ]
        if not summaries:
            return None

        content = str(summaries[-1].content)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if state.get("last_archived_summary_hash") == digest:
            return None

        result = runtime.context.memory.append_history(content, kind="summary")
        if inspect.isawaitable(result):
            await result
        return {"last_archived_summary_hash": digest}




