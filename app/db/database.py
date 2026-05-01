import os
from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings
from app.core.logger import log

# 全局引擎和会话工厂
engine: Optional[AsyncEngine] = None
async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


class Base(DeclarativeBase):
    """ORM 声明基类"""
    pass


async def init_db() -> None:
    """初始化 SQLite 数据库引擎和会话工厂"""
    global engine, async_session_factory

    if not settings.sqlite_db_path:
        raise RuntimeError("sqlite_db_path 未配置，请在 .env 中设置")

    # 确保数据目录存在
    db_dir = os.path.dirname(settings.sqlite_db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    db_url = f"sqlite+aiosqlite:///{settings.sqlite_db_path}"

    engine = create_async_engine(
        db_url,
        echo=settings.env == "dev",
        connect_args={"check_same_thread": False},
    )
    async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # 开启 WAL 模式，提升并发读写性能
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    # 自动创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.info(f"SQLite 数据库已初始化: {settings.sqlite_db_path}")


async def close_db() -> None:
    """关闭数据库引擎，释放资源"""
    global engine
    if engine:
        await engine.dispose()
        log.info("SQLite 数据库连接已关闭")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """依赖注入：提供异步数据库会话，自动 commit/rollback/close"""
    if async_session_factory is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
