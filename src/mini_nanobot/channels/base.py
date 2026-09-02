"""Channel 抽象基类。

对应 nanobot 的 `nanobot/channels/base.py`。每个具体 channel（Console、以后
可能的 Telegram/Discord……）要做两件事：

1. `start()`：监听平台消息，收到后调用 `_handle_message()` 转发进总线
2. `send()` / `send_delta()`：把总线里的回复，用平台的方式发出去

AgentService 只认总线，不认 channel；channel 只认平台 API，不认 agent 内部
是怎么跑的。两边完全解耦。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from typing import Any

from ..bus import MessageBus, InboundMessage


class BaseChannel(ABC):
    name: str = "base"
    supports_streaming: bool = False

    def __init__(self, bus: MessageBus) -> None:
        self.bus = bus
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """开始监听平台消息（长期运行的协程）。"""

    @abstractmethod
    async def stop(self) -> None:
        """停止监听、清理资源。"""

    @abstractmethod
    async def send(self, session_id: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        """发送一条完整的回复。"""

    async def _handle_message(
        self,
        session_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        meta = dict(metadata or {})
        meta.setdefault("supports_stream", self.supports_streaming)
        await self.bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                session_id=session_id,
                content=content,
                metadata=meta,
            )
        )
    
    @property
    def is_running(self) -> bool:
        return self._running

    

    


    
