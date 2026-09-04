"""立即提交异步子任务的 spawn 工具。"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from ..subagents import SubagentManager


def make_spawn_tool(manager: SubagentManager):
    @tool
    async def spawn(task: str, config: RunnableConfig) -> str:
        """异步提交子任务并立即返回 task_id。

        子代理看不到父对话，task 必须包含完成任务所需的全部上下文。
        """
        configurable = config.get("configurable") or {}
        parent_session_id = configurable.get("thread_id")
        if not isinstance(parent_session_id, str) or not parent_session_id:
            raise ValueError(
                "运行配置缺少有效的 configurable.thread_id"
            )
        record = manager.submit(parent_session_id, task)
        return f"子任务已提交，task_id：{record.task_id}"

    return spawn