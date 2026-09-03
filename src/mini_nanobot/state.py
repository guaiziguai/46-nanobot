"""主 Agent 的持久化状态与单次运行上下文。

`AgentState` 扩展 LangChain `create_agent` 的标准状态，而不是重新定义消息
reducer。这里仅保留必须跨模型调用/进程重启持久化的业务状态；模型调用次数之类的
单次运行预算交给 `ModelCallLimitMiddleware`，避免旧实现把计数累计到整个 thread。

`AgentContext` 是 LangGraph 的 runtime context，不进入 checkpoint。它承载当前
session、记忆后端和 pending queue 等运行期对象，工具和 middleware 都可以读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from langchain.agents.middleware import AgentState as LangChainAgentState
from typing_extensions import NotRequired


class PendingEventSource(Protocol):
    """pending queue 的最小读取协议，避免 middleware 依赖具体 SessionManager。"""

    async def drain_pending(self, session_id: str, *, limit: int = 3) -> list[Any]:
        """取出等待注入当前会话的事件。"""


class MemoryReader(Protocol):
    """动态提示词和摘要归档所需的最小记忆协议。"""

    def read_all_memory_files(self) -> Any:
        """读取三份 Markdown；允许同步兼容层或异步后端。"""

    def append_history(self, summary: str, *, kind: str = "summary") -> Any:
        """归档一条压缩摘要。"""


class AgentState(LangChainAgentState[Any]):
    """`create_agent` 与外层 Goal 图共享的 checkpoint 状态。"""

    goal_state: NotRequired[dict[str, Any] | None]
    continuation_count: NotRequired[int]
    empty_response_count: NotRequired[int]
    last_archived_summary_hash: NotRequired[str]
    goal_creation_allowed: NotRequired[bool]


@dataclass(slots=True)
class AgentContext:
    """一次图调用的非持久化依赖与授权信息。"""

    session_id: str
    memory: MemoryReader
    pending: PendingEventSource | None = None
    goal_creation_allowed: bool = False
    force_compact: bool = False
