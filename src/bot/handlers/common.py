"""Общие команды: /start, /help, /cancel."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.di import AppContext
from src.bot.keyboards import age_gate_kb, base_consent_kb, nsfw_consent_kb
from src.database.models import User as DbUser

router = Router()

WELCOME_TEXT = (
    "Привет! Я — Лилит 🌸\n\n"
    "Я виртуальный ИИ-компаньон: вымышленный персонаж, а не реальный человек. "
    "У меня нет тела и сознания, но есть характер, чувство юмора и хорошая память 😊\n\n"
    "Важно:\n"
    "• Я общаюсь только со взрослыми (18+);\n"
    "• эротический режим — добровольный и включается отдельно;\n"
    "• твои данные можно полностью удалить командой /forget_me.\n\n"
    "Продолжим? Подтверди, что тебе есть 18 лет."
)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if user is not None:
        # Незавершённый онбординг — продолжаем с нужного шага
        if user.consent_step == "base_pending":
            await bot.send_message(
                chat_id=message.chat.id,
                text=app_ctx.consent.base_policy_text(),
                reply_markup=base_consent_kb(),
            )
            return
        if user.consent_step == "nsfw_question":
            await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    "Мы остановились на вопросе про NSFW-режим 🔞\n\n"
                    "Он включается только отдельным согласием, доступен только "
                    "совершеннолетним и никогда не активируется автоматически."
                ),
                reply_markup=nsfw_consent_kb(),
            )
            return
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "С возвращением! 🌸 Я помню наш разговор.\nСписок команд — /help, настройки — /settings, режим — /mode."
            ),
        )
        return
    await bot.send_message(chat_id=message.chat.id, text=WELCOME_TEXT, reply_markup=age_gate_kb())


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot) -> None:
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "📖 Команды:\n"
            "/start — начало и возрастная проверка\n"
            "/profile — твой профиль и известные мне предпочтения\n"
            "/settings — изменить имя, интересы, границы\n"
            "/mode — режим: дружеский, флирт, романтический, NSFW\n"
            "/voice — голосовые ответы вкл/выкл\n"
            "/photo — нарисовать изображение персонажа\n"
            "/memory — категории сохранённых воспоминаний\n"
            "/reset — начать диалог заново (память сохранится)\n"
            "/forget_me — безвозвратно удалить все мои данные о тебе\n"
            "/privacy — политика обработки данных\n"
            "/cancel — отменить текущее действие\n\n"
            "Просто пиши мне сообщения — я отвечу 💬"
        ),
    )


@router.message(Command("version"))
async def cmd_version(message: Message, bot: Bot) -> None:
    from src.config import APP_VERSION

    await bot.send_message(
        chat_id=message.chat.id,
        text=f"🤖 Версия бота: {APP_VERSION}\nУстановщика: см. шапку окна при запуске.",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, bot: Bot, state: FSMContext) -> None:
    if await state.get_state() is None:
        await bot.send_message(chat_id=message.chat.id, text="Отменять нечего 🙂")
        return
    await state.clear()
    await bot.send_message(chat_id=message.chat.id, text="✅ Отменено.")


@router.callback_query(F.data == "photo:cancel")
async def cb_photo_cancel(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await bot.answer_callback_query(callback_query_id=cb.id, text="Отменено")
