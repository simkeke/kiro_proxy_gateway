from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.config import settings
from app.core.logger import log


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：初始化和释放资源"""
    from app.db import init_db, close_db
    from app.channels.registry import init_registry, shutdown_registry
    from app.gateway.router import init_router
    from app.gateway.throttle import init_throttle

    log.info("AI Gateway 启动中...")

    # 初始化 SQLite
    await init_db()

    # 打印 banner
    banner_path = Path(__file__).parent.parent / "banner.txt"
    if banner_path.exists():
        print(banner_path.read_text(encoding="utf-8"))

    # 初始化通道注册中心
    await init_registry(settings.channels_config_path)

    # 初始化模型路由器
    init_router()

    # 初始化限流器
    init_throttle()

    log.info("AI Gateway 启动完成")

    yield

    # 释放资源
    await shutdown_registry()
    await close_db()

    log.info("AI Gateway 已关闭")
