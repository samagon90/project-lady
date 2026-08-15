"""Команды: /profile, /settings, /mode, /voice, /photo, /memory, /reset, /forget_me, /privacy."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from src.bot.di import AppContext
from src.bot.keyboards import (
    confirm_kb,
    mode_kb,
    photo_cancel_kb,
    settings_kb,
    voice_kb,
)
from src.bot.states import PhotoStates, SettingsStates
from src.database.models import User as DbUser
from src.database.repositories import PreferencesRepository
from src.prompts import MODE_LABELS

router = Router()

_MODE_NAMES = {0: "🤝 Дружеский", 1: "😉 Лёгкий флирт", 2: "💞 Романтический", 3: "🔞 NSFW"}


def _require_user(user: DbUser | None) -> bool:
    return user is not None and user.consent_step == "active"


# ===================================================================== /profile


@router.message(Command("profile"))
async def cmd_profile(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    async with app_ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
        consent_info = await app_ctx.consent.consent_info(user)
    memory = await app_ctx.memory.overview(user)
    total_facts = sum(memory["counts"].values())
    lines = [
        "👤 Твой профиль:",
        f"• Имя: {prefs.name or '—'} (обращение: «{prefs.address_term}»)",
        f"• Местоимения: {prefs.pronouns or '—'}",
        f"• Язык: {prefs.language or 'ru'}",
        f"• Режим: {_MODE_NAMES.get(prefs.mode, prefs.mode)}",
        f"• Голосовые: {'вкл' if prefs.voice_enabled else 'выкл'}",
        f"• Интересы: {prefs.interests or '—'}",
        f"• Границы: {prefs.boundaries or '—'}",
        "",
        "📜 Согласия:",
        f"• Флирт/романтика: {consent_info['base_date'] or '—'} (v{consent_info['base_version'] or '—'})",
        f"• NSFW: {consent_info['nsfw_date'] or '—'} (v{consent_info['nsfw_version'] or '—'})",
        "",
        f"🧠 Воспоминаний: {total_facts}",
    ]
    await bot.send_message(chat_id=message.chat.id, text="\n".join(lines))


# ===================================================================== /settings


@router.message(Command("settings"))
async def cmd_settings(message: Message, bot: Bot, user: DbUser | None) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    await bot.send_message(
        chat_id=message.chat.id,
        text="⚙️ Что изменить? (отправь текст после выбора, /cancel — отмена)",
        reply_markup=settings_kb(),
    )


_SETTINGS_LABELS = {
    "name": "👤 Имя",
    "address": "💬 Обращение",
    "pronouns": "🏳️ Местоимения",
    "interests": "❤️ Интересы",
    "boundaries": "🚧 Границы",
}


async def _ask_setting(cb: CallbackQuery, bot: Bot, state: FSMContext, key: str) -> None:
    await state.set_state(_STATE_BY_KEY[key])
    await bot.answer_callback_query(callback_query_id=cb.id)
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else cb.from_user.id,
        text=f"Отправь новое значение для «{_SETTINGS_LABELS[key]}» (или /cancel):",
    )


_STATE_BY_KEY = {
    "name": SettingsStates.name,
    "address": SettingsStates.address_term,
    "pronouns": SettingsStates.pronouns,
    "interests": SettingsStates.interests,
    "boundaries": SettingsStates.boundaries,
}


@router.callback_query(F.data.startswith("settings:"))
async def cb_settings(cb: CallbackQuery, bot: Bot, state: FSMContext, app_ctx: AppContext, user: DbUser | None) -> None:
    key = (cb.data or "").removeprefix("settings:")
    if key == "done":
        await state.clear()
        await bot.answer_callback_query(callback_query_id=cb.id, text="Настройки закрыты")
        return
    if not _require_user(user):
        await bot.answer_callback_query(callback_query_id=cb.id, text="Сначала /start", show_alert=True)
        return
    if key in _STATE_BY_KEY:
        await _ask_setting(cb, bot, state, key)
    else:
        await bot.answer_callback_query(callback_query_id=cb.id, text="Неизвестная настройка")


@router.message(StateFilter(SettingsStates.name))
async def set_name(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None, state: FSMContext) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    value = (message.text or "").strip()[: app_ctx.settings.max_name_length]
    if not value:
        await bot.send_message(chat_id=message.chat.id, text="Пустое значение — попробуй ещё раз.")
        return
    async with app_ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(user, name=value)
    await state.clear()
    await bot.send_message(chat_id=message.chat.id, text=f"✅ Запомнила: «{value}».")


@router.message(StateFilter(SettingsStates.address_term))
async def set_address(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None, state: FSMContext) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    value = (message.text or "").strip().lower()[:16]
    if value not in ("ты", "вы"):
        await bot.send_message(chat_id=message.chat.id, text="Напиши «ты» или «вы».")
        return
    async with app_ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(user, address_term=value)
    await state.clear()
    await bot.send_message(chat_id=message.chat.id, text=f"✅ Буду обращаться на «{value}».")


@router.message(StateFilter(SettingsStates.pronouns))
async def set_pronouns(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None, state: FSMContext) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    value = (message.text or "").strip()[:64]
    async with app_ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(user, pronouns=value)
    await state.clear()
    await bot.send_message(chat_id=message.chat.id, text="✅ Местоимения сохранены.")


@router.message(StateFilter(SettingsStates.interests))
async def set_interests(
    message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None, state: FSMContext
) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    value = (message.text or "").strip()[:1000]
    async with app_ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(user, interests=value)
    await state.clear()
    await bot.send_message(chat_id=message.chat.id, text="✅ Интересы сохранены. Буду учитывать!")


@router.message(StateFilter(SettingsStates.boundaries))
async def set_boundaries(
    message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None, state: FSMContext
) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    value = (message.text or "").strip()[: app_ctx.settings.max_boundaries_length]
    async with app_ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(user, boundaries=value)
    await state.clear()
    await bot.send_message(
        chat_id=message.chat.id,
        text="✅ Границы сохранены. Обещаю их уважать 🤝",
    )


# ===================================================================== /mode


@router.message(Command("mode"))
async def cmd_mode(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    async with app_ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
    await bot.send_message(
        chat_id=message.chat.id,
        text="🎚 Выбери режим общения:",
        reply_markup=mode_kb(prefs.mode),
    )


@router.callback_query(F.data.startswith("mode:set:"))
async def cb_mode_set(cb: CallbackQuery, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await bot.answer_callback_query(callback_query_id=cb.id, text="Сначала /start", show_alert=True)
        return
    assert user is not None
    mode = int((cb.data or "").removeprefix("mode:set:"))
    if mode not in MODE_LABELS:
        await bot.answer_callback_query(callback_query_id=cb.id, text="Неизвестный режим")
        return
    if mode == 3 and not await app_ctx.consent.has_nsfw_consent(user):
        await bot.answer_callback_query(
            callback_query_id=cb.id,
            text="Сначала нужно принять отдельное NSFW-согласие",
            show_alert=True,
        )
        await app_ctx.consent.complete_onboarding(user)
        await bot.send_message(
            chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
            text=(
                "🔞 NSFW-режим требует отдельного согласия — оно не включается "
                "автоматически и доступно только совершеннолетним.\n\n" + app_ctx.consent.nsfw_policy_text()
            ),
            reply_markup=_nsfw_prompt_kb(),
        )
        return
    async with app_ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(user, mode=mode)
    await bot.answer_callback_query(callback_query_id=cb.id, text=f"Режим: {_MODE_NAMES[mode]}")
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
        text=f"✅ Режим: {_MODE_NAMES[mode]}. {_mode_hint(mode)}",
    )
    await app_ctx.audit.log("mode_changed", user=user, meta={"mode": mode})


def _mode_hint(mode: int) -> str:
    return {
        0: "Общаемся по-дружески 🤝",
        1: "Добавляю игривости 😉",
        2: "Включаю романтику 💞",
        3: "Взрослый режим — только по обоюдному желанию, с уважением к границам.",
    }[mode]


def _nsfw_prompt_kb():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔞 Показать условия NSFW", callback_data="consent:nsfw:show")]]
    )


# ===================================================================== /avatar

@router.message(Command("avatar"))
async def cmd_avatar(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    from pathlib import Path

    async with app_ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
    avatar = (
        Path("assets/lilith_avatar_anime.png")
        if prefs.image_style == "anime"
        else Path("assets/lilith_avatar.png")
    )
    path = app_ctx.settings.resolve_path(avatar)
    if not path.exists():
        await bot.send_message(chat_id=message.chat.id, text="Аватар не найден 😔")
        return
    await bot.send_photo(
        chat_id=message.chat.id,
        photo=FSInputFile(str(path)),
        caption=(
            "🖤 Это я — Лилит. "
            + ("🖌 рисованный стиль" if prefs.image_style == "anime" else "📸 реалистичный")
            + ". Смени стиль: /style"
        ),
    )


# ===================================================================== /style

@router.message(Command("style"))
async def cmd_style(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    async with app_ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "🎨 Стиль изображений и аватара Лилит:\n"
            f"Сейчас: {'📸 реалистичный' if prefs.image_style == 'realistic' else '🖌 рисованный (аниме)'}\n\n"
            "Переключай на лету:"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📸 Реалистичный", callback_data="style:realistic"),
                    InlineKeyboardButton(text="🖌 Рисованный (аниме)", callback_data="style:anime"),
                ]
            ]
        ),
    )


@router.callback_query(F.data.startswith("style:"))
async def cb_style(cb: CallbackQuery, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await bot.answer_callback_query(callback_query_id=cb.id, text="Сначала /start", show_alert=True)
        return
    assert user is not None
    style = (cb.data or "").removeprefix("style:")
    if style not in ("realistic", "anime"):
        await bot.answer_callback_query(callback_query_id=cb.id, text="Неизвестный стиль")
        return
    async with app_ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(user, image_style=style)
    label = "реалистичный" if style == "realistic" else "аниме"
    await bot.answer_callback_query(callback_query_id=cb.id, text=f"Стиль: {label}")
    # Показываем аватар в новом стиле
    avatar = (
        app_ctx.settings.resolve_path(__import__("pathlib").Path("assets/lilith_avatar_anime.png"))
        if style == "anime"
        else app_ctx.settings.resolve_path(__import__("pathlib").Path("assets/lilith_avatar.png"))
    )
    if avatar.exists():
        await bot.send_photo(
            chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
            photo=FSInputFile(str(avatar)),
            caption=(
                "Мой аватар: 🖌 рисованный. Теперь и все картинки будут в этом стиле!"
                if style == "anime"
                else "Мой аватар: 📸 реалистичный. Теперь и все картинки будут в этом стиле!"
            ),
        )
    await app_ctx.audit.log("style_changed", user=user, meta={"style": style})


# ===================================================================== /voice


@router.message(Command("voice"))
async def cmd_voice(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    async with app_ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
    await bot.send_message(
        chat_id=message.chat.id,
        text=(f"🎙 Голосовые ответы (локальный TTS Piper): {'включены' if prefs.voice_enabled else 'выключены'}."),
        reply_markup=voice_kb(prefs.voice_enabled),
    )


@router.callback_query(F.data == "voice:toggle")
async def cb_voice_toggle(cb: CallbackQuery, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await bot.answer_callback_query(callback_query_id=cb.id, text="Сначала /start", show_alert=True)
        return
    assert user is not None
    async with app_ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
        new_value = not prefs.voice_enabled
        await PreferencesRepository(session).update_fields(user, voice_enabled=new_value)
    await bot.answer_callback_query(callback_query_id=cb.id, text=f"Голос: {'вкл' if new_value else 'выкл'}")
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
        text=f"🎙 Голосовые ответы: {'включены' if new_value else 'выключены'}.",
        reply_markup=voice_kb(new_value),
    )


# ===================================================================== /photo


@router.message(Command("photo"))
async def cmd_photo(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None, state: FSMContext) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    prompt_text = (message.text or "").removeprefix("/photo").strip()
    if prompt_text:
        await _submit_photo(message, bot, app_ctx, user, prompt_text)
        return
    await state.set_state(PhotoStates.prompt)
    await bot.send_message(
        chat_id=message.chat.id,
        text="🎨 Что нарисовать? Опиши сцену, настроение, одежду. Например: «Лилит в осеннем парке, тёплый вечер»",
        reply_markup=photo_cancel_kb(),
    )


@router.message(StateFilter(PhotoStates.prompt), F.text)
async def photo_prompt_text(
    message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None, state: FSMContext
) -> None:
    await state.clear()
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    await _submit_photo(message, bot, app_ctx, user, message.text or "")


async def _submit_photo(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser, text: str) -> None:
    text = text.strip()
    if len(text) > app_ctx.settings.max_photo_prompt_length:
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"Слишком длинный запрос — максимум {app_ctx.settings.max_photo_prompt_length} символов.",
        )
        return
    result = await app_ctx.image_service.submit(user, text, message.message_id)
    if not result.ok:
        await bot.send_message(chat_id=message.chat.id, text=result.refusal_text or "Не получилось.")
        return
    await bot.send_message(
        chat_id=message.chat.id,
        text="🎨 Изображение создаётся… Обычно это занимает от 30 секунд до нескольких минут. Я пришлю его сюда.",
    )


# ===================================================================== /memory


@router.message(Command("memory"))
async def cmd_memory(message: Message, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    assert user is not None
    overview = await app_ctx.memory.overview(user)
    counts = overview["counts"]
    from src.services.memory import CATEGORY_LABELS_RU

    lines = ["🧠 Мои воспоминания о тебе:", ""]
    if not counts:
        lines.append("Пока пусто — но я запоминаю всё важное по ходу разговора 🙂")
    for category in ("profile", "preferences", "boundaries", "relationship", "events", "conversation_style"):
        count = counts.get(category, 0)
        lines.append(f"• {CATEGORY_LABELS_RU[category]}: {count}")
    lines.append("")
    lines.append("Последние факты:")
    for item in overview["recent"][:5]:
        lines.append(f"• [{CATEGORY_LABELS_RU.get(item['category'], item['category'])}] {item['fact'][:150]}")
    lines.append("")
    lines.append("Управление: /settings — изменить, /reset — сбросить диалог, /forget_me — удалить всё.")
    await bot.send_message(chat_id=message.chat.id, text="\n".join(lines))


# ===================================================================== /reset


@router.message(Command("reset"))
async def cmd_reset(message: Message, bot: Bot, user: DbUser | None) -> None:
    if not _require_user(user):
        await _not_registered(message, bot)
        return
    await bot.send_message(
        chat_id=message.chat.id,
        text="🔄 Начать диалог заново? Память о тебе (предпочтения, факты) сохранится.",
        reply_markup=confirm_kb("reset"),
    )


@router.callback_query(F.data == "reset:yes")
async def cb_reset_yes(cb: CallbackQuery, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if not _require_user(user):
        await bot.answer_callback_query(callback_query_id=cb.id, text="Сначала /start", show_alert=True)
        return
    assert user is not None
    await app_ctx.chat.reset_conversation(user)
    await bot.answer_callback_query(callback_query_id=cb.id, text="Диалог сброшен")
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
        text="✅ Начнём с чистого листа! О чём поговорим?",
    )


@router.callback_query(F.data == "reset:no")
async def cb_reset_no(cb: CallbackQuery, bot: Bot) -> None:
    await bot.answer_callback_query(callback_query_id=cb.id, text="Отменено")
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else cb.from_user.id,
        text="Хорошо, продолжаем как есть 🙂",
    )


# ===================================================================== /forget_me


@router.message(Command("forget_me"))
async def cmd_forget_me(message: Message, bot: Bot, user: DbUser | None) -> None:
    if user is None:
        await bot.send_message(
            chat_id=message.chat.id,
            text="За меня можно не беспокоиться — я о тебе ничего не знаю 🙂",
        )
        return
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "⚠️ Это действие необратимо.\n\n"
            "Будут удалены: профиль, согласия, сообщения, воспоминания, "
            "сгенерированные файлы и записи аудита. Ты начнёшь с чистого листа "
            "при следующем /start.\n\n"
            "Точно удалить?"
        ),
        reply_markup=confirm_kb("forget"),
    )


@router.callback_query(F.data == "forget:yes")
async def cb_forget_yes(cb: CallbackQuery, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if user is None:
        await bot.answer_callback_query(callback_query_id=cb.id, text="Нечего удалять")
        return
    await app_ctx.delete_user_data(user)
    await bot.answer_callback_query(callback_query_id=cb.id, text="Данные удалены")
    try:
        await bot.send_message(
            chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
            text="🗑 Всё удалено: профиль, сообщения, память и файлы.\n\nЕсли захочешь вернуться — /start.",
        )
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data == "forget:no")
async def cb_forget_no(cb: CallbackQuery, bot: Bot) -> None:
    await bot.answer_callback_query(callback_query_id=cb.id, text="Отменено")
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else cb.from_user.id,
        text="Хорошо, ничего не удаляю 🙂",
    )


# ===================================================================== /privacy


@router.message(Command("privacy"))
async def cmd_privacy(message: Message, bot: Bot, app_ctx: AppContext) -> None:
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "🔐 Политика обработки данных\n\n"
            "Что хранится (локально, на сервере бота):\n"
            "• профиль и предпочтения (имя, обращение, интересы, границы);\n"
            "• история переписки и извлечённые из неё воспоминания;\n"
            f"• временные аудио/изображения (удаляются через {app_ctx.settings.media_ttl_hours} ч);\n"
            "• обезличенный журнал аудита (без текста сообщений).\n\n"
            "Доступ:\n"
            "• /profile — что я знаю о тебе;\n"
            "• /memory — воспоминания по категориям;\n"
            "• /settings — изменить данные;\n"
            "• /forget_me — безвозвратно удалить всё.\n\n"
            "Данные не передаются третьим лицам и не публикуются. Модели работают "
            "локально на сервере бота."
        ),
    )


# ===================================================================== helpers


async def _not_registered(message: Message, bot: Bot) -> None:
    await bot.send_message(
        chat_id=message.chat.id,
        text="Сначала нужно пройти короткую регистрацию: нажми /start 🌸",
    )
