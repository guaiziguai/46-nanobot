"""非阻塞分派消息，并在成功 run 后按阈值执行 Dream。"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import HumanMessage

from .bus import InboundMessage, MessageBus, OutboundMessage
from .session import RunStatus
from .state import AgentContext

logger = logging.getLogger("mini_nanobot")


class AgentService:
    def __init__(self, bus: MessageBus, runtime) -> None:
        self.bus = bus
        self.runtime = runtime
        self._tasks: set[asyncio.Task[None]] = set()
        self._dream_lock = asyncio.Lock()

    async def run(self) -> None:
        try:
            while True:
                msg = await self.bus.consume_inbound()
                try:
                    await self._dispatch(msg)
                except Exception as exc:
                    logger.exception("处理消息失败")
                    await self._reply(msg, f"处理失败：{exc}")
        finally:
            for task in self._tasks:
                task.cancel()
            if self._tasks:
                await asyncio.gather(
                    *self._tasks,
                    return_exceptions=True,
                )

    async def _dispatch(self, msg: InboundMessage) -> None:
        if self.runtime.sessions.get(msg.session_id) is None:
            self.runtime.sessions.create(
                "外部会话",
                thread_id=msg.session_id,
            )

        content = msg.content.strip()
        if self.runtime.sessions.run_status(
            msg.session_id
        ) is not RunStatus.IDLE:
            await self.runtime.sessions.enqueue(
                msg.session_id,
                "user_message",
                content,
                {"channel": msg.channel},
            )
            return
        self._start_run(msg, content)

    def _start_run(
        self,
        msg: InboundMessage,
        content: str,
    ) -> None:
        task = asyncio.create_task(
            self._run_managed(msg, content),
            name=f"mini-nanobot:{msg.session_id}",
        )
        try:
            self.runtime.sessions.start_run(msg.session_id, task)
        except BaseException:
            task.cancel()
            raise
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_managed(
        self,
        msg: InboundMessage,
        content: str,
    ) -> None:
        try:
            async with self.runtime.sessions.lock_for(msg.session_id):
                await self._run_once(msg, content)
                await self._maybe_run_auto_dream()
        except asyncio.CancelledError:
            logger.info("会话运行已取消：%s", msg.session_id)
        except Exception as exc:
            logger.exception("处理消息失败")
            await self._reply(msg, f"处理失败：{exc}")
        finally:
            self.runtime.sessions.finish_run(msg.session_id)

    async def _run_once(
        self,
        msg: InboundMessage,
        content: str,
    ) -> None:
        context = AgentContext(
            session_id=msg.session_id,
            memory=self.runtime.memory,
            pending=self.runtime.sessions,
        )
        result = await self.runtime.graph.ainvoke(
            {"messages": [HumanMessage(content=content)]},
            config={"configurable": {"thread_id": msg.session_id}},
            context=context,
        )
        final_content = (
            self._message_text(result["messages"][-1])
            or "模型连续返回空响应，请稍后重试。"
        )
        await self._reply(msg, final_content)

    async def _maybe_run_auto_dream(self) -> None:
        threshold = self.runtime.dream_auto_threshold
        if threshold <= 0 or self._dream_lock.locked():
            return
        async with self._dream_lock:
            try:
                history = await self.runtime.memory.read_history()
                cursor = await self.runtime.memory.get_dream_cursor()
                if len(history) - cursor < threshold:
                    return
                from .memory.dream import run_dream

                result = await run_dream(
                    self.runtime.llm,
                    self.runtime.memory,
                )
                logger.info("自动 Dream 完成：%s", result)
            except Exception:
                logger.exception("自动 Dream 失败")

    @staticmethod
    def _message_text(message: object) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict)
                and block.get("type") in {"text", "output_text"}
            )
        return str(content) if content is not None else ""

    async def _reply(
        self,
        msg: InboundMessage,
        content: str,
    ) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                session_id=msg.session_id,
                content=content,
            )
        )

