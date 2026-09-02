"""独立会话管理基础。

持久化层只负责会话元数据，运行锁、待处理事件和任务句柄保留在进程内。
通过 ``SessionMetadataStore`` 协议可在以后替换为 Redis 等后端。
"""
import asyncio
import json
import os
import tempfile
import threading
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable


def _utc_now() -> str:
    """返回便于 JSON 保存、带时区的 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True, slots=True)
class SessionInfo:
    """可持久化的会话元数据。"""

    thread_id: str
    title: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """会话事件。待处理的事件"""

    thread_id: str
    event: str
    data: dict[str, Any]
    created_at: str


@runtime_checkable
class SessionMetadataStore(Protocol):
    """元数据存储协议；Redis 后端只需实现这两个同步短 I/O 方法。"""

    def load(self) -> dict[str, Any]:
        """加载完整元数据快照。"""
        ...

    def save(self, data: Mapping[str, Any]) -> None:
        """原子保存完整元数据快照。"""
        ...






