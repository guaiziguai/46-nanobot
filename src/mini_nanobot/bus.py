"""消息总线：解耦「Channel」和「AgentService」。

对应 nanobot 的 `nanobot/bus/queue.py` + `nanobot/bus/events.py`。
不是真正的发布订阅系统，只是两个 `asyncio.Queue`：

    Channel --publish_inbound--> [inbound queue] --consume_inbound--> AgentService
    AgentService --publish_outbound--> [outbound queue] --consume_outbound--> Channel

这样 Channel 完全不需要知道 AgentService 内部在做什么（压缩、重试、工具调用……），
AgentService 也完全不需要知道消息是从 CLI 来的还是以后从 Telegram 来的。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass,field

from typing import Any


@dataclass

class InboundMessage:
    """入站消息。流向agentserver"""

    channel: str
    session_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """出站消息。流向channel"""

    channel: str
    session_id: str
    content: str
    event: str = "final"  # "final" | "delta" | "stream_end" | "error"
    metadata: dict[str, Any] = field(default_factory=dict)


class MessageBus:
    """两个队列：入站和出站。"""

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        return await self.outbound.get()




