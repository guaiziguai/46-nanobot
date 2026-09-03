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



#锁+原子写入

def _directory_lock(path: Path) -> threading.RLock:
    """同一目录的多个后端实例也必须共用一把进程内锁。"""
    key = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _atomic_write(path: Path, content: str) -> None:
    """在目标目录写临时文件，落盘后以 replace 原子替换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)


#路径
def _namespace_dir(root: Path, namespace: str | None) -> Path:
    if namespace is None or namespace == "":
        return root
    relative = Path(namespace)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("namespace 必须是安全的相对路径")
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("namespace 不能逃逸记忆根目录") from exc
    return target


#读写我们的history.jsonl

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _read_history(directory: Path) -> list[dict[str, Any]]:
    text = _read_text(directory / "history.jsonl")
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _append_history(directory: Path, summary: str, kind: str) -> dict[str, Any]:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "content": summary,
    }
    path = directory / "history.jsonl"
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _directory_lock(directory):
        previous = _read_text(path)
        separator = "\n" if previous and not previous.endswith(("\n", "\r")) else ""
        _atomic_write(path, previous + separator + line)
    return entry


#读写我们的.dream_cursor
def _validate_cursor(cursor: int, history_size: int) -> None:
    if isinstance(cursor, bool) or not isinstance(cursor, int):
        raise TypeError("dream cursor 必须是整数")
    if cursor < 0 or cursor > history_size:
        raise ValueError(f"dream cursor 必须在 0..{history_size} 之间")


def _get_cursor(directory: Path) -> int:
    raw = _read_text(directory / ".dream_cursor").strip()
    try:
        cursor = int(raw or "0")
    except ValueError:
        return 0
    if cursor < 0:
        return 0
    return min(cursor, len(_read_history(directory)))


def _set_cursor(directory: Path, cursor: int) -> None:
    with _directory_lock(directory):
        _validate_cursor(cursor, len(_read_history(directory)))
        _atomic_write(directory / ".dream_cursor", str(cursor))


#目录不存在就建；某份 md 已存在则不要覆盖（用户手改过的 USER.md 必须保住）.

def _load_bundled_template(name: str) -> str | None:
    with suppress(Exception):
        tpl = resources.files("mini_nanobot") / "workspace/memory" / name
        if tpl.is_file():
            return tpl.read_text(encoding="utf-8")
    return None


def _fallback_content(name: str) -> str:
    titles = {
        "SOUL.md": "# SOUL —— agent 行为规则\n\n（Dream 会往这里写：工具使用策略、行为准则）\n",
        "USER.md": "# USER —— 用户画像\n\n（Dream 会往这里写：用户身份、偏好、沟通风格）\n",
        "MEMORY.md": "# MEMORY —— 项目/世界知识\n\n（Dream 会往这里写：项目上下文、长期事实）\n",
    }
    return titles.get(name, f"# {name}\n")


def _default_content(name: str) -> str:
    return _load_bundled_template(name) or _fallback_content(name)



 
#缺文件读空串；写文件走目录锁 + _atomic_write。snapshot/restore 只动三份 md。
def _validate_memory_name(name: str) -> None:
    if name not in MEMORY_FILES:
        raise ValueError(f"不支持的记忆文件：{name}")


def _initialize(directory: Path) -> None:
    lock = _directory_lock(directory)
    with lock:
        directory.mkdir(parents=True, exist_ok=True)
        for name in MEMORY_FILES:
            path = directory / name
            if not path.exists():
                _atomic_write(path, _default_content(name))


def _write_text(directory: Path, path: Path, content: str) -> None:
    with _directory_lock(directory):
        _atomic_write(path, content)


def _snapshot(directory: Path) -> MemorySnapshot:
    return {name: _read_text(directory / name) for name in MEMORY_FILES}


def _restore(directory: Path, snapshot: Mapping[str, str]) -> None:
    if set(snapshot) != set(MEMORY_FILES):
        raise ValueError(f"快照必须且只能包含：{', '.join(MEMORY_FILES)}")
    if not all(isinstance(content, str) for content in snapshot.values()):
        raise TypeError("快照内容必须是字符串")
    with _directory_lock(directory):
        for name in MEMORY_FILES:
            _atomic_write(directory / name, snapshot[name])




class FileMemoryBackend:
    """基于本地目录的异步记忆后端。

    未传 ``namespace`` 时文件仍位于 ``memory_dir``，兼容原来的目录布局；
    传入后则存放在 ``memory_dir / namespace``。
    """

    def __init__(self, memory_dir: Path | str):
        self.memory_dir = Path(memory_dir)

    def namespace_dir(self, namespace: str | None = None) -> Path:
        return _namespace_dir(self.memory_dir, namespace)

    def history_path(self, namespace: str | None = None) -> Path:
        return self.namespace_dir(namespace) / "history.jsonl"

    async def initialize(self, namespace: str | None = None) -> None:
        await asyncio.to_thread(_initialize, self.namespace_dir(namespace))

    async def read_memory_file(self, name: str, namespace: str | None = None) -> str:
        _validate_memory_name(name)
        return await asyncio.to_thread(
            _read_text, self.namespace_dir(namespace) / name
        )

    async def write_memory_file(
        self, name: str, content: str, namespace: str | None = None
    ) -> None:
        _validate_memory_name(name)
        directory = self.namespace_dir(namespace)
        await asyncio.to_thread(_write_text, directory, directory / name, content)

    async def read_all_memory_files(
        self, namespace: str | None = None
    ) -> dict[str, str]:
        return await asyncio.to_thread(_snapshot, self.namespace_dir(namespace))

    async def append_history(
        self, summary: str, *, kind: str = "summary", namespace: str | None = None
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            _append_history, self.namespace_dir(namespace), summary, kind
        )

    async def read_history(
        self, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(_read_history, self.namespace_dir(namespace))

    async def read_history_since(
        self, cursor: int, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        if isinstance(cursor, bool) or not isinstance(cursor, int):
            raise TypeError("history cursor 必须是整数")
        if cursor < 0:
            raise ValueError("history cursor 不能为负数")
        return (await self.read_history(namespace))[cursor:]

    async def get_dream_cursor(self, namespace: str | None = None) -> int:
        return await asyncio.to_thread(_get_cursor, self.namespace_dir(namespace))

    async def set_dream_cursor(
        self, cursor: int, namespace: str | None = None
    ) -> None:
        await asyncio.to_thread(_set_cursor, self.namespace_dir(namespace), cursor)

    async def snapshot(self, namespace: str | None = None) -> MemorySnapshot:
        return await self.read_all_memory_files(namespace)

    async def restore(
        self, snapshot: Mapping[str, str], namespace: str | None = None
    ) -> None:
        await asyncio.to_thread(_restore, self.namespace_dir(namespace), snapshot)

    async def has_changes(
        self, snapshot: Mapping[str, str], namespace: str | None = None
    ) -> bool:
        return await self.snapshot(namespace) != dict(snapshot)

    # 语义更明确的别名，便于 Dream 调用点迁移。
    snapshot_content = snapshot
    restore_content = restore
    content_has_changed = has_changes

class MemoryStore:
    """旧同步 API 的兼容外观；新代码应使用 ``FileMemoryBackend``。"""

    def __init__(self, memory_dir: Path | str):
        self.memory_dir = Path(memory_dir)
        _initialize(self.memory_dir)

    @property
    def history_path(self) -> Path:
        return self.memory_dir / "history.jsonl"

    @property
    def _cursor_path(self) -> Path:
        return self.memory_dir / ".dream_cursor"

    def read_memory_file(self, name: str) -> str:
        _validate_memory_name(name)
        return _read_text(self.memory_dir / name)

    def write_memory_file(self, name: str, content: str) -> None:
        _validate_memory_name(name)
        _write_text(self.memory_dir, self.memory_dir / name, content)

    def read_all_memory_files(self) -> dict[str, str]:
        return _snapshot(self.memory_dir)

    def append_history(self, summary: str, *, kind: str = "summary") -> dict[str, Any]:
        return _append_history(self.memory_dir, summary, kind)

    def read_history(self) -> list[dict[str, Any]]:
        return _read_history(self.memory_dir)

    def read_history_since(self, cursor: int) -> list[dict[str, Any]]:
        if isinstance(cursor, bool) or not isinstance(cursor, int):
            raise TypeError("history cursor 必须是整数")
        if cursor < 0:
            raise ValueError("history cursor 不能为负数")
        return self.read_history()[cursor:]

    def get_dream_cursor(self) -> int:
        return _get_cursor(self.memory_dir)

    def set_dream_cursor(self, cursor: int) -> None:
        _set_cursor(self.memory_dir, cursor)

    def snapshot(self) -> MemorySnapshot:
        return _snapshot(self.memory_dir)

    def restore(self, snapshot: Mapping[str, str]) -> None:
        _restore(self.memory_dir, snapshot)

    def has_changes(self, snapshot: Mapping[str, str]) -> bool:
        return self.snapshot() != dict(snapshot)

    snapshot_content = snapshot
    restore_content = restore
    content_has_changed = has_changes




