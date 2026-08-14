"""Обработка обычных текстовых сообщений: диалог с персонажем."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message

from src.bot.di import AppContext
from src.bot.states import PhotoStates, SettingsStates
from src.database.models import User as DbUser
from src.database.repositories import PreferencesRepository
from src.providers.base import LLMUnavailable

logger = logging.getLogger(__name__)

router = Router()

# Пока пользователь редактирует настройки — его тексты идут в FSM-хендлеры
_FSM_STATES = (
    SettingsStates.name,
    SettingsStates.address_term,
    SettingsStates.pronouns,
    SettingsStates.interests,
    SettingsStates.boundaries,
    PhotoStates.prompt,
)


@router.message(
    F.text,
    ~F.text.regexp(r"^/"),
    StateFilter(*_FSM_STATES),
)
async def on_text_fsm(message: Message, bot: Bot, state: FSMContext) -> None:
    """Текст во время FSM-операции — игнорируем с подсказкой /cancel."""
    current = await state.get_state()
    labels = {
        "SettingsStates:name": "имя",
        "SettingsStates:address_term": "обращение",
        "SettingsStates:pronouns": "местоимения",
        "SettingsStates:interests": "интересы",
        "SettingsStates:boundaries": "границы",
        "PhotoStates:prompt": "запрос картинки",
    }
    label = labels.get(current or "", "действие")
    await bot.send_message(
        chat_id=message.chat.id,
        text=f"Сначала заверши текущее действие ({label}) или отправь /cancel.",
    )


@router.message(F.text, ~F.text.regexp(r"^/"))
async def on_text(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if user is None or user.consent_step != "active":
        await bot.send_message(
            chat_id=message.chat.id,
            text="Сначала познакомимся: нажми /start 🌸",
        )
        return
    text = message.text or ""
    if len(text) > app_ctx.settings.max_message_length:
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"Сообщение слишком длинное (максимум {app_ctx.settings.max_message_length} символов).",
        )
        return

    try:
        result = await app_ctx.chat.handle_message(user, text, message.message_id)
    except LLMUnavailable:
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "😔 Моя языковая модель сейчас недоступна (локальный сервер Ollama "
                "не отвечает). Попробуй через пару минут — текстовый режим вернётся."
            ),
        )
        return

    if not result.text:
        return

    await bot.send_message(chat_id=message.chat.id, text=result.text)

    # Голосовое сообщение (текст + voice), при недоступности TTS — только текст
    if result.voice_text:
        async with app_ctx.db.session() as session:
            prefs = await PreferencesRepository(session).get_or_create(user)
        if prefs.voice_enabled:
            ogg_path = await app_ctx.tts.build_voice(result.voice_text, speed=prefs.voice_speed)
            if ogg_path is not None:
                try:
                    await bot.send_voice(
                        chat_id=message.chat.id,
                        voice=FSInputFile(str(ogg_path)),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Не удалось отправить голосовое: %s", exc)
                finally:
                    app_ctx.storage.remove(ogg_path)
