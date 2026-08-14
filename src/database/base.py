"""Движок и сессии БД. SQLite для разработки, PostgreSQL — опционально."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")

    def _poolclass(self):
        if self.is_sqlite:
            if ":memory:" in self.url:
                return StaticPool
            return NullPool
        return None

    async def connect(self) -> None:
        kwargs = {}
        if self._poolclass() is not None:
            kwargs["poolclass"] = self._poolclass()
        if self.is_sqlite:
            kwargs["connect_args"] = {"timeout": 30}
        self.engine = create_async_engine(self.url, **kwargs)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        # Проверяем подключение
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("База данных подключена: %s", self.url)

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Сессия с автоматическим commit/rollback."""
        assert self.session_factory is not None, "Database.connect() не вызван"
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
