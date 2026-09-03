from __future__ import annotations

from langchain_core.prompts import PromptTemplate

_MAIN_TEMPLATE = PromptTemplate.from_template(
    "你是 mini-nanobot，一个小巧、有帮助的 AI agent。\n"
    "当工具能帮到你时就调用工具，回答尽量简洁，默认使用中文回复。\n"
    "只有当用户明确要求你持续处理、一直做到完成的长期任务时，才调用 create_goal；"
    "普通的一次性问答不需要创建目标。\n"
    "\n"
    "## 长期记忆（Dream 巩固产生，仅作为你的背景参考，不要原文念给用户）\n"
    "### 行为规则（SOUL.md）\n{soul}\n\n"
    "### 用户画像（USER.md）\n{user}\n\n"
    "### 项目知识（MEMORY.md）\n{memory}\n"
    "{goal_section}"
)


def build_system_prompt(memory_files: dict[str, str], goal_state: dict[str, object] | None) -> str:
    """主 agent 的 system prompt：身份规则 + 当前长期记忆 + （如果有）进行中的目标。

    `memory_files` 就是 `MemoryStore.read_all_memory_files()` 的返回值，调用方
    每次构造 prompt 前都重新读一次文件，所以 Dream 刚更新完记忆，下一轮对话立刻
    就能用上最新内容——不需要额外的缓存失效逻辑。
    """
    goal_section = ""
    if goal_state and goal_state.get("status") == "active":
        goal_section = f"\n## 当前进行中的目标\n{goal_state.get('objective', '')}\n"
    return _MAIN_TEMPLATE.format(
        soul=memory_files.get("SOUL.md") or "（暂无）",
        user=memory_files.get("USER.md") or "（暂无）",
        memory=memory_files.get("MEMORY.md") or "（暂无）",
        goal_section=goal_section,
    )