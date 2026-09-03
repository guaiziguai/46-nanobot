from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from contextlib import suppress  #临时抑制异常
from datetime import datetime, timezone  #时间
from importlib import resources  #导入资源
from pathlib import Path  #路径
from typing import Any, Mapping, Protocol, runtime_checkable  #类型

MEMORY_FILES = ("SOUL.md", "USER.md", "MEMORY.md")
MemorySnapshot = dict[str, str]

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@runtime_checkable
class MemoryBackend(Protocol):
    """可替换的异步记忆持久化协议。"""

    async def initialize(self, namespace: str | None = None) -> None: ...

    async def read_memory_file(self, name: str, namespace: str | None = None) -> str: ...

    async def write_memory_file(
        self, name: str, content: str, namespace: str | None = None
    ) -> None: ...

    async def read_all_memory_files(
        self, namespace: str | None = None
    ) -> dict[str, str]: ...

    async def append_history(
        self, summary: str, *, kind: str = "summary", namespace: str | None = None
    ) -> dict[str, Any]: ...

    async def read_history(self, namespace: str | None = None) -> list[dict[str, Any]]: ...

    async def read_history_since(
        self, cursor: int, namespace: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def get_dream_cursor(self, namespace: str | None = None) -> int: ...

    async def set_dream_cursor(
        self, cursor: int, namespace: str | None = None
    ) -> None: ...

    async def snapshot(self, namespace: str | None = None) -> MemorySnapshot: ...

    async def restore(
        self, snapshot: Mapping[str, str], namespace: str | None = None
    ) -> None: ...

    async def has_changes(
        self, snapshot: Mapping[str, str], namespace: str | None = None
    ) -> bool: ...