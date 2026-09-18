"""异步数据库引擎与事务边界。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tara_agent.config import Settings


class DatabaseConfigurationError(RuntimeError):
    """数据库配置缺失或不合法。"""


class Database:
    """集中管理连接池，并为每个业务操作提供独立事务。"""

    def __init__(self, settings: Settings) -> None:
        try:
            database_url = settings.get_database_url()
        except ValueError as error:
            raise DatabaseConfigurationError(str(error)) from error

        self._engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        """返回 Alembic 集成或诊断所需的异步引擎。"""

        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """在成功时提交事务，在异常时回滚事务。"""

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def ping(self) -> None:
        """执行最小查询以确认数据库连接可用。"""

        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        """释放当前进程持有的全部数据库连接。"""

        await self._engine.dispose()
