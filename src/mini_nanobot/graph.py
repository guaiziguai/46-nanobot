from __future__ import annotations

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from .config import AppConfig, load_config
from .prompts import build_system_prompt
from .tools import BASIC_TOOLS

from contextlib import asynccontextmanager  #异步的上下文管理器
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver #异步的sqlite检查点保存器

from .state import AgentContext, AgentState
from .middleware import build_agent_middleware

def build_llm(cfg: AppConfig) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=cfg.provider.api_key,
        base_url=cfg.provider.api_base,
        model=cfg.provider.model,
        temperature=cfg.provider.temperature,
        max_tokens=cfg.provider.max_tokens,
        timeout=cfg.provider.timeout_seconds,
    )



@asynccontextmanager
async def create_app(cfg: AppConfig):
    llm = build_llm(cfg)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(cfg.db_path)) as saver:
        # create_agent 通常要在 compile 时带 checkpointer
        # 按你安装的 langchain 版本：
        # - 有的版本 create_agent(..., checkpointer=saver)
        # - 有的返回未编译图，再 .compile(checkpointer=saver)
        graph = create_agent(
            model=llm,
            tools=BASIC_TOOLS,
            system_prompt=build_system_prompt(),
            checkpointer=saver,
            name="react_agent",
            state_schema=AgentState,
            context_schema=AgentContext,
            middleware=build_agent_middleware(llm, context_window=cfg.context_window, consolidation_ratio=cfg.consolidation_ratio, max_model_calls=cfg.max_model_calls),
        )
        yield graph




