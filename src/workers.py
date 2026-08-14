"""Фоновые воркеры: очередь генерации изображений и периодическая очистка.

Очередь — asyncio.Queue + статусы задач в БД. При рестарте задачи со
статусом queued автоматически подхватываются заново.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot

from src.config import Settings
from src.database.base import Database
from src.database.repositories import AssetRepository, JobRepository
from src.services.image import ImageService
from src.services.storage import StorageService
from src.utils import utcnow

logger = logging.getLogger(__name__)


class GenerationWorker:
    """Исполняет очередь генерации изображений (limit = IMAGE_MAX_WORKERS)."""

    def __init__(
        self,
        queue: asyncio.Queue[int],
        image_service: ImageService,
        db: Database,
        bot: Bot,
        stop_event: asyncio.Event,
    ) -> None:
        self.queue = queue
        self.image_service = image_service
        self.db = db
        self.bot = bot
        self.stop_event = stop_event

    async def run(self) -> None:
        await self._requeue_stale()
        logger.info("Воркер генерации запущен")
        while not self.stop_event.is_set():
            try:
                job_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await self.image_service.run_job(job_id, self.bot)
            except Exception:  # noqa: BLE001 — воркер живёт дальше
                logger.exception("Ошибка обработки задачи %s", job_id)
            finally:
                self.queue.task_done()

    async def _requeue_stale(self) -> None:
        """После рестарта возвращает в очередь незавершённые задачи."""
        async with self.db.session() as session:
            jobs = await JobRepository(session).queued_jobs()
        for job in jobs:
            try:
                self.queue.put_nowait(job.id)
            except asyncio.QueueFull:
                break
        if jobs:
            logger.info("Вернул в очередь %s задач после рестарта", len(jobs))


class RetentionWorker:
    """Периодическая очистка: временные файлы, ассеты, старые воспоминания."""

    def __init__(
        self,
        db: Database,
        storage: StorageService,
        settings: Settings,
        stop_event: asyncio.Event,
    ) -> None:
        self.db = db
        self.storage = storage
        self.settings = settings
        self.stop_event = stop_event

    async def run(self) -> None:
        interval = max(1, self.settings.retention_interval_minutes) * 60
        logger.info("Воркер очистки запущен (интервал %s мин)", interval // 60)
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            try:
                await self.cleanup_once()
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка периодической очистки")

    async def cleanup_once(self) -> None:
        # 1. Временные файлы
        self.storage.cleanup_expired(timedelta(hours=self.settings.media_ttl_hours))
        # 2. Просроченные ассеты (файлы + записи)
        now = utcnow()
        async with self.db.session() as session:
            assets = await AssetRepository(session).expired(now, limit=200)
            for asset in assets:
                self.storage.unlink_if_exists(asset.file_path)
                await AssetRepository(session).delete(asset)
            if assets:
                logger.info("Удалено просроченных ассетов: %s", len(assets))
        # 3. Просроченные воспоминания (у всех пользователей)
        from typing import cast

        from sqlalchemy import CursorResult, delete

        from src.database.models import MemoryItem

        async with self.db.session() as session:
            result = await session.execute(
                delete(MemoryItem).where(MemoryItem.expires_at.is_not(None), MemoryItem.expires_at < now)
            )
            deleted = (cast(CursorResult, result)).rowcount or 0
            if deleted:
                logger.info("Удалено просроченных воспоминаний: %s", deleted)
        logger.debug("Периодическая очистка завершена")


def start_workers(
    ctx,
    bot: Bot,
) -> list[asyncio.Task]:
    """Запускает воркеры как фоновые задачи."""
    tasks = []
    for _ in range(max(1, ctx.settings.image_max_workers)):
        worker = GenerationWorker(
            ctx.image_service.queue,
            ctx.image_service,
            ctx.db,
            bot,
            ctx.stop_event,
        )
        tasks.append(asyncio.create_task(worker.run()))
    retention = RetentionWorker(ctx.db, ctx.storage, ctx.settings, ctx.stop_event)
    tasks.append(asyncio.create_task(retention.run()))
    return tasks


async def stop_workers(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
