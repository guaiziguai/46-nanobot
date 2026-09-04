from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .config import AppConfig
from .memory import FileMemoryBackend, MemoryBackend
from .middleware import build_agent_middleware
from .session import SessionManager
from .state import AgentContext, AgentState
from .subagents import SubagentManager
from .tools import BASIC_TOOLS, make_spawn_tool


def build_llm(cfg: AppConfig) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=cfg.provider.api_key,
        base_url=cfg.provider.api_base,
        model=cfg.provider.model,
        temperature=cfg.provider.temperature,
        max_tokens=cfg.provider.max_tokens,
        timeout=cfg.provider.timeout_seconds,
    )



@dataclass
class AppRuntime:
    graph: object
    llm: object
    memory: MemoryBackend
    sessions: SessionManager
    subagents: SubagentManager
    dream_auto_threshold: int  #未巩固条数 = len(history) - dream_cursor

@asynccontextmanager
async def create_app(cfg: AppConfig):
    llm = build_llm(cfg)
    memory = FileMemoryBackend(cfg.memory_dir)
    await memory.initialize()
    sessions = SessionManager(data_dir=cfg.workspace_dir)

    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(cfg.db_path)) as saver:
        subagents = SubagentManager(
            llm,
            BASIC_TOOLS,
            sessions,
            max_concurrent=cfg.max_concurrent_subagents,
            timeout=cfg.subagent_timeout_seconds,
        )
        spawn_tool = make_spawn_tool(subagents)
        graph = create_agent(
            llm,
            tools=[*BASIC_TOOLS, spawn_tool],
            middleware=build_agent_middleware(
                llm,
                context_window=cfg.context_window,
                consolidation_ratio=cfg.consolidation_ratio,
                max_model_calls=cfg.max_iterations,
            ),
            state_schema=AgentState,
            context_schema=AgentContext,
            checkpointer=saver,
            name="react_agent",
        )
        try:
            yield AppRuntime(
                graph=graph,
                llm=llm,
                memory=memory,
                sessions=sessions,
                subagents=subagents,
                dream_auto_threshold=cfg.dream_auto_threshold,
            )
        finally:
            await subagents.close()




