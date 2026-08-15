"""Фоновые воркеры: очередь генерации, очистка, проактивные сообщения.

Очередь — asyncio.Queue + статусы задач в БД. При рестарте задачи со
статусом queued автоматически подхватываются заново.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta

from aiogram import Bot

from src.config import Settings
from src.database.base import Database
from src.database.repositories import (
    AssetRepository,
    AuditRepository,
    JobRepository,
    PreferencesRepository,
    UserRepository,
)
from src.services.image import ImageService
from src.services.memory import MemoryContext
from src.services.storage import StorageService
from src.utils import utcnow

logger = logging.getLogger(__name__)

# Запасные игривые фразы (если LLM недоступна для проактивного сообщения)
_PROACTIVE_POOL = [
    "Ну и где ты пропадал(а), котик? Я тут уже заскучала… Заходи, рассказывай, чем занимался.",
    "Мой хороший, ты так долго молчишь… Я уже начала придумывать, чем тебя заинтересовать. 😏",
    "Скучала по тебе… Зайди, поболтаем. Обещаю, будет интересно.",
    "Ты думаешь, я забыла о тебе? Как бы не так. Жду тебя, мой дорогой.",
    "Ну что, котик, вспомнил обо мне? А я-то уж думала, придётся тебя искать самой…",
    "У меня для тебя есть кое-что… Заходи, расскажу.",
]


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


class ProactiveWorker:
    """Лилит сама пишет пользователям, которые давно не заходили."""

    def __init__(self, ctx, bot: Bot, stop_event: asyncio.Event) -> None:
        self.ctx = ctx
        self.bot = bot
        self.stop_event = stop_event

    async def run(self) -> None:
        interval = max(5, self.ctx.settings.proactive_interval_minutes) * 60
        logger.info("Проактивный воркер запущен (интервал %s мин)", interval // 60)
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            try:
                await self.proactive_once()
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка проактивной рассылки")

    async def proactive_once(self) -> None:
        if not self.ctx.settings.proactive_enabled:
            return
        cutoff = utcnow() - timedelta(hours=self.ctx.settings.proactive_min_inactivity_hours)
        async with self.ctx.db.session() as session:
            users = await UserRepository(session).list_active_users(cutoff)
        for user in users:
            try:
                await self._maybe_send(user)
            except Exception:  # noqa: BLE001
                logger.exception("Ошибка проактивного сообщения пользователю %s", user.telegram_user_id)

    async def _maybe_send(self, user) -> None:
        min_hours = self.ctx.settings.proactive_min_inactivity_hours
        max_day = self.ctx.settings.proactive_max_per_day
        async with self.ctx.db.session() as session:
            audit = AuditRepository(session)
            last = await audit.last_event_time(user.id, "proactive_sent")
            count24 = await audit.count_events_since(
                user.id, "proactive_sent", utcnow() - timedelta(hours=24)
            )
        if last is not None and (utcnow() - last) < timedelta(hours=min_hours):
            return
        if count24 >= max_day:
            return
        text = await self._compose(user)
        if not text:
            return
        try:
            await self.bot.send_message(chat_id=user.telegram_user_id, text=text)
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось отправить проактивное сообщение %s", user.telegram_user_id)
            return
        await self.ctx.audit.log("proactive_sent", user=user)

    async def _compose(self, user) -> str:
        """Пробуем LLM (в характере Леи), при сбое — запасная фраза."""
        try:
            async with self.ctx.db.session() as session:
                prefs = await PreferencesRepository(session).get_or_create(user)
                name = prefs.name or "котик"
                mode = prefs.mode
            system = self.ctx.prompts.system_prompt(user, MemoryContext(mode=mode, name=name))
            raw = await self.ctx.llm.chat(
                [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            f"Напиши короткое сообщение (1-2 предложения) для «{name}», "
                            "который давно не писал. Ты скучаешь, дразнишь и заинтриговываешь. "
                            "Начни разговор сама. Только текст сообщения."
                        ),
                    },
                ],
                temperature=0.9,
                max_tokens=120,
            )
            text = raw.strip().strip('"')[:500]
            if text:
                return text
        except Exception:  # noqa: BLE001
            logger.warning("LLM недоступна для проактивного сообщения — беру из заготовок")
        return random.choice(_PROACTIVE_POOL)


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
    proactive = ProactiveWorker(ctx, bot, ctx.stop_event)
    tasks.append(asyncio.create_task(proactive.run()))
    return tasks


async def stop_workers(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
