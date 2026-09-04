from __future__ import annotations


import asyncio
import logging

from .bus import MessageBus
from .channels import ChannelManager, ConsoleChannel
from .config import ConfigurationError, load_config
from .service import AgentService
from .session import SessionManager
from .graph import create_app

logging.basicConfig(level=logging.WARNING)

async def _main() -> None:
    cfg = load_config()
    cfg.ensure_dirs()
    bus = MessageBus()

    async with create_app(cfg) as runtime:
        console = ConsoleChannel(bus, runtime.sessions)
        manager = ChannelManager(bus, [console])
        service = AgentService(bus, runtime)
        service_task = asyncio.create_task(service.run())
        await manager.start()
        try:
            await manager.wait_until_all_stopped()
        finally:
            service_task.cancel()
            await manager.stop()
            await asyncio.gather(service_task, return_exceptions=True)


def run() -> None:
    try:
        asyncio.run(_main())
    except ConfigurationError as exc:
        print(f"启动失败：{exc}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()


