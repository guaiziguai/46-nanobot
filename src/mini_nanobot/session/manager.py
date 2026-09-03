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


    def _save_locked(self) -> None:
        self._store.save(self._data)

    def _require_runtime(self, thread_id: str) -> _SessionRuntime:
        with self._guard:
            if thread_id not in self._data["sessions"]:
                raise KeyError(f"会话不存在：{thread_id}")
            return self._runtime[thread_id]

    def _info_locked(self, thread_id: str) -> SessionInfo:
        return SessionInfo(**self._data["sessions"][thread_id])

    

    def create(self, title: str = "新会话", *, thread_id: str | None = None) -> SessionInfo:
        """创建新会话。"""
        if thread_id is None:
            thread_id = uuid.uuid4().hex
        if thread_id in self._data["sessions"]:
            raise ValueError(f"会话已存在：{thread_id}")

        now = _utc_now()
        with self._guard:
            if thread_id in self._data["sessions"]:
                raise ValueError(f"thread_id 已存在：{thread_id}")
            info = SessionInfo(thread_id, title.strip() or "新会话", now, now)
            self._data["sessions"][thread_id] = asdict(info)
            self._runtime[thread_id] = _SessionRuntime()
            previous_active = self._data["active_thread_id"]
            if self._data["active_thread_id"] is None:
                self._data["active_thread_id"] = thread_id
            try:
                self._save_locked()
            except BaseException:
                del self._data["sessions"][thread_id]
                del self._runtime[thread_id]
                self._data["active_thread_id"] = previous_active
                raise
            return info
    def list(self) -> list[SessionInfo]:
        """按最近更新时间倒序列出会话。"""
        with self._guard:
            values = [SessionInfo(**value) for value in self._data["sessions"].values()]
        return sorted(values, key=lambda item: (item.updated_at, item.thread_id), reverse=True)

    def get(self, thread_id: str) -> SessionInfo | None:
        with self._guard:
            value = self._data["sessions"].get(thread_id)
            return SessionInfo(**value) if value is not None else None

    @property
    def active_thread_id(self) -> str | None:
        with self._guard:
            return self._data["active_thread_id"]

    def get_active(self) -> SessionInfo | None:
        with self._guard:
            thread_id = self._data["active_thread_id"]
            return self._info_locked(thread_id) if thread_id is not None else None

    def activate(self, thread_id: str) -> SessionInfo:
        """切换当前会话，并原子保存 active_thread_id。"""
        with self._guard:
            if thread_id not in self._data["sessions"]:
                raise KeyError(f"会话不存在：{thread_id}")
            previous = self._data["active_thread_id"]
            self._data["active_thread_id"] = thread_id
            try:
                self._save_locked()
            except BaseException:
                self._data["active_thread_id"] = previous
                raise
            return self._info_locked(thread_id)

    def delete(self, thread_id: str) -> bool:
        """删除会话；正在运行的任务必须先取消或结束。"""
        with self._guard:
            if thread_id not in self._data["sessions"]:
                return False
            runtime = self._runtime[thread_id]
            if runtime.status is not RunStatus.IDLE:
                raise RuntimeError("不能删除正在运行的会话")

            old_info = self._data["sessions"].pop(thread_id)
            old_active = self._data["active_thread_id"]
            del self._runtime[thread_id]
            if old_active == thread_id:
                remaining = self.list()
                self._data["active_thread_id"] = remaining[0].thread_id if remaining else None
            try:
                self._save_locked()
            except BaseException:
                self._data["sessions"][thread_id] = old_info
                self._data["active_thread_id"] = old_active
                self._runtime[thread_id] = runtime
                raise
            return True

    def lock_for(self, thread_id: str) -> asyncio.Lock:
        """取得会话专属锁，供未来执行图串行化同一会话请求。"""
        return self._require_runtime(thread_id).lock
    

    # 待处理事件管理

    async def enqueue(
        self,
        thread_id: str,
        event_type: str,
        content: Any,
        metadata: Mapping[str, Any] | None = None,
        *,
        event_id: str | None = None,
    ) -> PendingEvent:
        """加入待处理事件；同一 event_id 重复入队时保持幂等。"""
        runtime = self._require_runtime(thread_id)
        if event_id is None:
            event_id = uuid.uuid4().hex
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event_id 必须是非空字符串")
        async with runtime.pending_lock:
            # 避免重复事件
            if event_id in runtime.events_by_id:
                return runtime.events_by_id[event_id]
            event = PendingEvent(event_id, event_type, content, dict(metadata or {}))
            # 加入队列
            runtime.pending.append(event)
            runtime.events_by_id[event_id] = event
            self._touch(thread_id)
            return event

    async def drain(self, thread_id: str, limit: int | None = None) -> list[PendingEvent]:
        """按 FIFO 顺序取走待处理事件。"""
        if limit is not None and limit < 0:
            raise ValueError("limit 不能小于 0")
        runtime = self._require_runtime(thread_id)
        async with runtime.pending_lock:
            count = len(runtime.pending) if limit is None else min(limit, len(runtime.pending))
            return [runtime.pending.popleft() for _ in range(count)]

    async def drain_pending(
        self,
        session_id: str,
        *,
        limit: int = 3,
    ) -> list[PendingEvent]:
        """供 Agent middleware 使用的协议别名。"""
        return await self.drain(session_id, limit=limit)

    def pending_count(self, thread_id: str) -> int:
        """返回队列长度；精确修改仍由会话异步锁保护。"""
        return len(self._require_runtime(thread_id).pending)

    def _touch(self, thread_id: str) -> None:
        with self._guard:
            old = self._data["sessions"][thread_id]["updated_at"]
            self._data["sessions"][thread_id]["updated_at"] = _utc_now()
            try:
                self._save_locked()
            except BaseException:
                self._data["sessions"][thread_id]["updated_at"] = old
                raise

    def start_run(
        self,
        thread_id: str,
        task: asyncio.Task[Any] | None = None,
    ) -> None:
        """标记运行中，并可登记用于取消的 asyncio.Task。"""
        runtime = self._require_runtime(thread_id)
        if runtime.status is not RunStatus.IDLE:
            raise RuntimeError("会话已经在运行")
        if task is not None and task.done():
            raise ValueError("不能登记已结束的任务")
        runtime.status = RunStatus.RUNNING
        runtime.task = task

    def finish_run(self, thread_id: str) -> None:
        runtime = self._require_runtime(thread_id)
        runtime.status = RunStatus.IDLE
        runtime.task = None

    def run_status(self, thread_id: str) -> RunStatus:
        return self._require_runtime(thread_id).status

    def run_task(self, thread_id: str) -> asyncio.Task[Any] | None:
        return self._require_runtime(thread_id).task

    def cancel_run(self, thread_id: str) -> bool:
        """请求取消任务；调用方应在任务收尾后调用 finish_run。"""
        runtime = self._require_runtime(thread_id)
        task = runtime.task
        if runtime.status is RunStatus.IDLE or task is None or task.done():
            return False
        runtime.status = RunStatus.CANCELLING
        task.cancel()
        return True


    
    
    

    


    

    


































