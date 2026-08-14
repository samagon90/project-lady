"""Миделвари: защита от групп, rate limit, внедрение контекста."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.bot.di import AppContext
from src.config import Settings
from src.database.repositories import UserRepository

logger = logging.getLogger(__name__)

HandlerType = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class ContextMiddleware:
    """Прокидывает AppContext в хендлеры (data['app_ctx'])."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def __call__(self, handler: HandlerType, event: TelegramObject, data: dict[str, Any]) -> Any:
        data["app_ctx"] = self.ctx
        return await handler(event, data)


class ChatTypeMiddleware:
    """Бот работает только в личных сообщениях. Из групп — вежливый отказ."""

    async def __call__(self, handler: HandlerType, event: TelegramObject, data: dict[str, Any]) -> Any:
        chat = _chat_of(event)
        if chat is not None and chat.type != "private":
            bot: Bot = data["bot"]
            if isinstance(event, Message):
                await bot.send_message(
                    chat_id=chat.id,
                    text="😊 Я работаю только в личных сообщениях. Напиши мне в личный чат — там и познакомимся!",
                )
            elif isinstance(event, CallbackQuery):
                await bot.answer_callback_query(
                    callback_query_id=event.id,
                    text="Я работаю только в личных сообщениях!",
                    show_alert=True,
                )
            return None
        return await handler(event, data)


class RateLimitMiddleware:
    """Скользящее окно: не больше N сообщений в минуту на пользователя."""

    def __init__(self, settings: Settings) -> None:
        self.limit = max(1, settings.rate_limit_messages_per_minute)
        self._buckets: dict[int, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def __call__(self, handler: HandlerType, event: TelegramObject, data: dict[str, Any]) -> Any:
        user_id = _user_id_of(event)
        if user_id is None:
            return await handler(event, data)
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.get(user_id)
            created = bucket is None
            if bucket is None:
                bucket = deque()
                self._buckets[user_id] = bucket
            while bucket and now - bucket[0] > 60.0:
                bucket.popleft()
            if not bucket and not created:
                # Окно истекло — убираем корзину из памяти: при следующем
                # сообщении создастся новая. Память не копится между
                # пользователями, у которых давно не было сообщений.
                self._buckets.pop(user_id, None)
            if len(bucket) >= self.limit:
                await self._notify_limited(event, data)
                return None
            bucket.append(now)
        return await handler(event, data)

    async def _notify_limited(self, event: TelegramObject, data: dict[str, Any]) -> None:
        bot: Bot = data["bot"]
        try:
            if isinstance(event, Message):
                await bot.send_message(
                    chat_id=event.chat.id,
                    text="⏳ Не так быстро! Подожди немного между сообщениями.",
                )
            elif isinstance(event, CallbackQuery):
                await bot.answer_callback_query(
                    callback_query_id=event.id,
                    text="⏳ Слишком часто, секундочку.",
                    show_alert=True,
                )
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось уведомить о rate limit")


class RegistrationMiddleware:
    """Загружает пользователя из БД в data['user'] (None, если не зарегистрирован)."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def __call__(self, handler: HandlerType, event: TelegramObject, data: dict[str, Any]) -> Any:
        user_id = _user_id_of(event)
        user = None
        if user_id is not None:
            async with self.ctx.db.session() as session:
                user = await UserRepository(session).get_by_telegram_id(user_id)
        data["user"] = user
        return await handler(event, data)


def _chat_of(event: TelegramObject) -> Any:
    if isinstance(event, Message):
        return event.chat
    if isinstance(event, CallbackQuery):
        return event.message.chat if event.message else None
    return None


def _user_id_of(event: TelegramObject) -> int | None:
    if isinstance(event, Message):
        return event.from_user.id if event.from_user else None
    if isinstance(event, CallbackQuery):
        return event.from_user.id
    return None
