from __future__ import annotations


import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


#参数点的严格的验证

class ConfigurationError(RuntimeError):
    """用户可修复的配置错误。"""
    pass


class ProviderConfig(BaseModel):
    """提供者配置。"""
    model_config = ConfigDict(validate_default=True)

    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    api_base: str = Field(
        default_factory=lambda: os.getenv(
            "OPENAI_API_BASE",
            "https://api.openai.com/v1",
        )
    )
    model: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", "gpt-4o-mini"))
    temperature: float = Field(
        default_factory=lambda: float(os.getenv("MODEL_TEMPERATURE", "0.7"))
    )
    max_tokens: int = Field(
        default_factory=lambda: int(os.getenv("MODEL_MAX_TOKENS", "4096")),
        ge=1,
    )
    timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("MODEL_TIMEOUT_SECONDS", "120")),
        gt=0,
    )

    @field_validator("api_base")
    @classmethod
    def validate_api_base(cls, value: str) -> str:

        value = value.strip().rstrip("/")

        if not value:
            raise ValueError("api_base不能为空")
        if any(
            m in value
            for m in ("[workspace-id]", "<workspace-id>", "{workspace_id}")
        ):raise ValueError("仍包含 workspace ID 占位符，请替换为真实值")

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OPENAI_API_BASE 必须是包含主机名的 http/https URL")
        return value



class AppConfig(BaseModel):
    """应用配置。"""
    provider: ProviderConfig = Field(default_factory=ProviderConfig)

    workspace_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("WORKSPACE_DIR", "./workspace")).resolve()
    )

    context_window: int = Field(
        default_factory=lambda: int(os.getenv("CONTEXT_WINDOW", "32000")))

    max_iterations: int = Field(default_factory=lambda: int(os.getenv("MAX_ITERATIONS", "25")))
    max_goal_continuations: int = Field(
        default_factory=lambda: int(os.getenv("MAX_GOAL_CONTINUATIONS", "12")),
        ge=0,
    )
    run_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("RUN_TIMEOUT_SECONDS", "600")),
        gt=0,
    )
    max_concurrent_subagents: int = Field(
        default_factory=lambda: int(os.getenv("MAX_CONCURRENT_SUBAGENTS", "3")),
        ge=1,
    )
    subagent_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("SUBAGENT_TIMEOUT_SECONDS", "300")),
        gt=0,
    )
    dream_auto_threshold: int = Field(
        default_factory=lambda: int(os.getenv("DREAM_AUTO_THRESHOLD", "10")),
        ge=0,
    )
    mcp_config_path: str = Field(default_factory=lambda: os.getenv("MCP_CONFIG_PATH", ""))

    


    @property
    def db_path(self) -> Path:
        return self.workspace_dir / "sessions.db"

    @property
    def memory_dir(self) -> Path:
        return self.workspace_dir / "memory"


    def ensure_dirs(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)




def load_config() -> AppConfig:
    load_dotenv()
    try:
        cfg = AppConfig()
    except ValidationError as e:
        raise ConfigurationError(f"配置验证失败: {e}") from e

    if not cfg.provider.api_key:
        raise ConfigurationError("OPENAI_API_KEY 未设置")
    

    cfg.ensure_dirs()

    return cfg
    

    
    





    





