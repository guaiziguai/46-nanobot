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

def _content_is_blank(content: Any) -> bool:
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        return not any(
            isinstance(block, dict)
            and block.get("type") in {"text", "output_text"}
            and str(block.get("text", "")).strip()
            for block in content
        )
    return content is None
    

class EmptyResponseRecoveryMiddleware(AgentMiddleware[AgentState, AgentContext]):
    """空响应最多重试两次，避免终端只显示一个空行。"""

    state_schema = AgentState

    async def abefore_agent(
        self,
        state: AgentState,
        runtime,
    ) -> dict[str, Any]:
        return {"empty_response_count": 0}

    @hook_config(can_jump_to=["model"])
    async def aafter_model(
        self,
        state: AgentState,
        runtime,
    ) -> dict[str, Any] | None:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return None
        if last.tool_calls or not _content_is_blank(last.content):
            return {"empty_response_count": 0}

        retries = state.get("empty_response_count", 0)
        if retries >= 2:
            return None
        return {"empty_response_count": retries + 1, "jump_to": "model"}


def _should_retry_model(exc: Exception) -> bool:
    return classify_error(exc, attempt=0).should_retry


# class PendingInjectionMiddleware(AgentMiddleware[AgentState, AgentContext]):
#     """在每次模型调用前注入用户补充或后台 Subagent 结果。"""

#     state_schema = AgentState

#     async def abefore_model(
#         self,
#         state: AgentState,
#         runtime,
#     ) -> dict[str, Any] | None:
#         context = runtime.context
#         if context.pending is None:
#             return None

#         events = await context.pending.drain_pending(context.session_id, limit=3)
#         if not events:
#             return None

#         messages: list[HumanMessage] = []
#         for event in events:
#             event_type = str(_event_value(event, "type", "external"))
#             content = str(_event_value(event, "content", "")).strip()
#             event_id = str(_event_value(event, "event_id", ""))
#             if not content:
#                 continue
#             messages.append(
#                 HumanMessage(
#                     content=f"[运行时注入：{event_type}]\n{content}",
#                     additional_kwargs={
#                         "injected_event": event_type,
#                         "event_id": event_id,
#                     },
#                 )
#             )
#         return {"messages": messages} if messages else None


def build_agent_middleware(
    llm: BaseChatModel,
    *,
    context_window: int,
    consolidation_ratio: float,
    max_model_calls: int,
) -> list[AgentMiddleware]:
    """构造主 Agent middleware，顺序决定模型调用前后的处理先后。"""

    trigger_tokens = max(1000, int(context_window * consolidation_ratio))
    keep_tokens = max(500, int(context_window * 0.2))

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

    middleware: list[AgentMiddleware] = [
        runtime_prompt,
        # PendingInjectionMiddleware(),
        ModelRetryMiddleware(
            max_retries=2,
            retry_on=_should_retry_model,
            on_failure="error",
        ),
        ToolRetryMiddleware(
            max_retries=1,
            tools=["calculator", "get_current_time", "read_text_file"],
            on_failure="continue",
        ),
        ModelCallLimitMiddleware(
            run_limit=max_model_calls,
            exit_behavior="end",
        ),
        ToolCallLimitMiddleware(
            run_limit=max_model_calls * 2,
            exit_behavior="continue",
        ),
        SummarizationMiddleware(
            llm,
            trigger=("tokens", trigger_tokens),
            keep=("tokens", keep_tokens),
        ),
        SummaryArchiveMiddleware(),
        EmptyResponseRecoveryMiddleware(),
    ]
    return middleware







