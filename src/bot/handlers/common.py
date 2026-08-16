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
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

        url = app_ctx.settings.webapp_url
        kb = None
        if url:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🖤 Открыть приложение Лилит",
                            web_app=WebAppInfo(url=url),
                        )
                    ]
                ]
            )
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "С возвращением! 🌸 Я помню наш разговор.\n"
                "Список команд — /help, настройки — /settings, режим — /mode."
                + (f"\n\n🖤 Мини-приложение: {url}" if url else "")
            ),
            reply_markup=kb,
        )
        return
    await bot.send_message(chat_id=message.chat.id, text=WELCOME_TEXT, reply_markup=age_gate_kb())


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot) -> None:
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "🖤 Я — Лилит. Вот что умею:\n\n"
            "💬 Просто пиши — я отвечаю, помню, меняю настроение\n"
            "🎨 «нарисуй…» / «покажи себя» — пришлю картинку\n"
            "📖 /diary — мой дневник о наших днях\n"
            "💜 /profile — уровень отношений и XP\n"
            "🔄 Кнопка под моим ответом — «другой вариант»\n\n"
            "Команды:\n"
            "/app — мини-приложение (чат, настройки, галерея)\n"
            "/profile — профиль, уровень отношений\n"
            "/settings — имя, интересы, границы\n"
            "/mode — режим: дружеский, флирт, романтика, NSFW\n"
            "/style — стиль картинок: реалистичный / аниме\n"
            "/voice — голосовые ответы вкл/выкл\n"
            "/photo — нарисовать изображение\n"
            "/video — короткое видео (AnimateDiff)\n"
            "/diary — дневник Лилит\n"
            "/memory — воспоминания\n"
            "/reset — начать диалог заново (память сохранится)\n"
            "/forget_me — удалить все данные о тебе\n"
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


@router.message(Command("app"))
async def cmd_app(message: Message, bot: Bot, app_ctx: AppContext) -> None:
    """Открывает Telegram Mini App (профиль, настройки, галерея)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    url = app_ctx.settings.webapp_url
    if not url:
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "🖤 Мини-приложение пока не настроено. Администратору: укажите "
                "WEBAPP_URL в .env (публичный HTTPS-адрес) и перезапустите бота."
            ),
        )
        return
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "🖤 Открой моё мини-приложение: профиль, настройки, галерея и память.\n\n"
            f"🔗 Ссылка (если кнопка не работает): {url}"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🖤 Открыть приложение Лилит",
                        web_app=WebAppInfo(url=url),
                    )
                ]
            ]
        ),
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
