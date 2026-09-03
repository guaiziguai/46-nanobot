from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage

from .bus import InboundMessage, MessageBus, OutboundMessage
from .state import AgentContext

logger = logging.getLogger("mini_nanobot")


class AgentService:
    def __init__(self, bus: MessageBus, graph) -> None:
        self.bus = bus
        self.agent = graph

    async def run(self) -> None:
        while True:
            msg = await self.bus.consume_inbound()
            try:
                await self._process(msg)
            except Exception as exc:
                logger.exception("处理失败")
                await self._reply(msg, f"处理失败：{exc}")
    

    async def _process(self, msg: InboundMessage) -> None:
        result = await self.agent.ainvoke(
            {"messages": [HumanMessage(content=msg.content)]},
            config={"configurable": {"thread_id": msg.session_id}},
        )
        content = str(result["messages"][-1].content)
        await self._reply(msg, content)

    async def _reply(self, msg: InboundMessage, content: str) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                session_id=msg.session_id,
                content=content,
            )
        )

    


          


