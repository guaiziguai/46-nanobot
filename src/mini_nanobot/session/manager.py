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
class PendingEvent:
    """等待某个会话处理的事件。event_id避免重复事件。"""

    event_id: str
    type: str
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """会话事件。待处理的事件"""

    thread_id: str
    event: str
    data: dict[str, Any]
    created_at: str


class RunStatus(StrEnum):
    """会话在当前进程中的运行状态。"""

    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"

@runtime_checkable
class SessionMetadataStore(Protocol):
    """元数据存储协议；Redis 后端只需实现这两个同步短 I/O 方法。"""

    def load(self) -> dict[str, Any]:
        """加载完整元数据快照。"""
        ...

    def save(self, data: Mapping[str, Any]) -> None:
        """原子保存完整元数据快照。"""
        ...



class JsonSessionMetadataStore:
    """使用本地原子 JSON 文件保存会话元数据。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "active_thread_id": None, "sessions": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取会话元数据：{self.path}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
            raise ValueError(f"会话元数据格式无效：{self.path}")
        return data

    def save(self, data: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        try:
            # Windows 下必须先关闭临时文件句柄，os.replace 才能稳定工作。
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise


@dataclass(slots=True)
class _SessionRuntime:
    """仅在当前进程存在的会话运行数据。"""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: deque[PendingEvent] = field(default_factory=deque)
    events_by_id: dict[str, PendingEvent] = field(default_factory=dict)
    status: RunStatus = RunStatus.IDLE
    task: asyncio.Task[Any] | None = None


class SessionManager:
    """会话管理器。"""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        store: SessionMetadataStore | None = None,
    ) -> None:
        if store is None:
            if data_dir is None:
                raise ValueError("data_dir 和 store 至少需要提供一个")
            store = JsonSessionMetadataStore(Path(data_dir) / "sessions.json")
        elif data_dir is not None:
            raise ValueError("data_dir 和 store 不能同时提供")

        self._store = store
        self._guard = threading.RLock()
        self._data = self._normalise(store.load())
        self._runtime: dict[str, _SessionRuntime] = {
            thread_id: _SessionRuntime() for thread_id in self._data["sessions"]
        }

    @staticmethod
    def _normalise(raw: Mapping[str, Any]) -> dict[str, Any]:
        """规范化原始元数据。"""
        sessions: dict[str, dict[str, str]] = {}
        for thread_id, value in raw.get("sessions", {}).items():
            if not isinstance(thread_id, str) or not isinstance(value, Mapping):
                continue
            try:
                info = SessionInfo(
                    thread_id=thread_id,
                    title=str(value["title"]),
                    created_at=str(value["created_at"]),
                    updated_at=str(value["updated_at"]),
                )
            except KeyError:
                continue
            sessions[thread_id] = asdict(info)

            active = raw.get("active_thread_id")
            if active not in sessions:
                active = None
            return {"version": 1, "active_thread_id": active, "sessions": sessions}


































