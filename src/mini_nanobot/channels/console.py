from __future__ import annotations

import asyncio
import uuid
from typing import Any

from rich.console import Console as RichConsole
from rich.markdown import Markdown

from ..bus import MessageBus
from .base import BaseChannel

_console = RichConsole()


HELP_TEXT = (
    "[bold]可用命令[/bold]\n"
    "  /new      开启一个新会话（新的 session_id，历史不再延续）\n"
    "  /goal 目标 创建并持续执行一个目标\n"
    "  /stop     停止当前会话正在执行的任务\n"
    "  /compact  手动触发一次上下文压缩（Consolidator）\n"
    "  /dream    手动触发一次长期记忆巩固（Dream）\n"
    "  /status   查看当前会话状态\n"
    "  /help     显示本帮助信息\n"
    "  /exit     退出\n"
)

class ConsoleChannel(BaseChannel):
    name = "console"
    supports_streaming = False

    def __init__(self, bus: MessageBus) -> None:
        super().__init__(bus)
        self.session_id = str(uuid.uuid4()).hex
    


    async def start(self) -> None:
        self._running = True

        _console.print("[bold cyan]mini-nanobot[/bold cyan] 输入 /help 查看命令\n")

        loop = asyncio.get_event_loop()

        while self._running:
            try:
                line = await loop.run_in_executor(
                    None, _console.input, "[bold green]you>[/bold green] "
                )
            except (EOFError, KeyboardInterrupt):
                self._running = False
                break

            line = line.strip()

            if not line:
                continue

            if line == "/exit":
                self._running = False
                break
            elif line == "/help":
                _console.print(HELP_TEXT)
            if line == "/new":
                self.session_id = uuid.uuid4().hex
                _console.print("[yellow]已开启新会话[/yellow]\n")
                continue
            await self._handle_message(self.session_id, line)
    
    async def stop(self) -> None:
        self._running = False

    async def send(
        self,
        session_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
    #非流式回复
        _console.print("[bold magenta]bot>[/bold magenta]")
        _console.print(Markdown(content) if content else "[dim](空回复)[/dim]")
        _console.print()

      






