"""Онбординг: age gate и согласия (базовая политика + отдельный NSFW opt-in)."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from src.bot.di import AppContext
from src.bot.keyboards import base_consent_kb, nsfw_after_consent_kb, nsfw_consent_kb
from src.database.models import User as DbUser

router = Router()


@router.callback_query(F.data == "age:ok")
async def cb_age_ok(cb: CallbackQuery, bot: Bot, app_ctx: AppContext) -> None:
    user_id = cb.from_user.id
    await app_ctx.consent.register(
        user_id,
        username=cb.from_user.username,
        first_name=cb.from_user.first_name,
    )
    await bot.answer_callback_query(callback_query_id=cb.id)
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else user_id,
        text=app_ctx.consent.base_policy_text(),
        reply_markup=base_consent_kb(),
    )


@router.callback_query(F.data == "age:exit")
async def cb_age_exit(cb: CallbackQuery, bot: Bot) -> None:
    await bot.answer_callback_query(callback_query_id=cb.id)
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else cb.from_user.id,
        text="Хорошо! Если передумаешь — просто напиши /start 🌸",
    )


@router.callback_query(F.data == "consent:base:ok")
async def cb_consent_base_ok(cb: CallbackQuery, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if user is None:
        await _please_start(cb, bot)
        return
    await app_ctx.consent.accept_base(user)
    await bot.answer_callback_query(callback_query_id=cb.id, text="Согласие сохранено ✅")
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
        text=(
            "Спасибо! Теперь пара слов про NSFW-режим 🔞\n\n"
            "Эротический режим не входит в основную политику — он включается "
            "только отдельным согласием и никогда не активируется автоматически. "
            "Он доступен только совершеннолетним и только в личных сообщениях."
        ),
        reply_markup=nsfw_consent_kb(),
    )


@router.callback_query(F.data == "consent:base:no")
async def cb_consent_base_no(cb: CallbackQuery, bot: Bot) -> None:
    await bot.answer_callback_query(callback_query_id=cb.id)
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else cb.from_user.id,
        text="Хорошо, без обид! Если захочешь начать — /start 🌸",
    )


@router.callback_query(F.data == "consent:nsfw:show")
async def cb_consent_nsfw_show(cb: CallbackQuery, bot: Bot, app_ctx: AppContext) -> None:
    await bot.answer_callback_query(callback_query_id=cb.id)
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else cb.from_user.id,
        text=app_ctx.consent.nsfw_policy_text(),
        reply_markup=nsfw_consent_kb(),
    )


@router.callback_query(F.data == "consent:nsfw:ok")
async def cb_consent_nsfw_ok(cb: CallbackQuery, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if user is None:
        await _please_start(cb, bot)
        return
    await app_ctx.consent.accept_nsfw(user)
    await app_ctx.consent.complete_onboarding(user)
    await bot.answer_callback_query(callback_query_id=cb.id, text="NSFW-согласие сохранено")
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
        text=(
            "Согласие на NSFW сохранено (версия политики записана).\n"
            "Оно не включает режим автоматически — включить можно сейчас или позже "
            "командой /mode."
        ),
        reply_markup=nsfw_after_consent_kb(),
    )


@router.callback_query(F.data == "consent:nsfw:no")
async def cb_consent_nsfw_no(cb: CallbackQuery, bot: Bot, app_ctx: AppContext, user: DbUser | None) -> None:
    if user is None:
        await _please_start(cb, bot)
        return
    await app_ctx.consent.complete_onboarding(user)
    await bot.answer_callback_query(callback_query_id=cb.id, text="NSFW остаётся выключенным")
    await bot.send_message(
        chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
        text=("Отлично, тогда общаемся в дружеском и романтическом ключе 💕\nЕсли передумаешь — /mode."),
    )


@router.callback_query(F.data == "consent:nsfw:later")
async def cb_consent_nsfw_later(cb: CallbackQuery, bot: Bot, user: DbUser | None) -> None:
    await bot.answer_callback_query(callback_query_id=cb.id, text="Ок!")
    if user is not None:
        await bot.send_message(
            chat_id=cb.message.chat.id if cb.message else user.telegram_user_id,
            text="Хорошо, режим можно включить позже командой /mode.",
        )


async def _please_start(cb: CallbackQuery, bot: Bot) -> None:
    await bot.answer_callback_query(callback_query_id=cb.id, text="Нажми /start, чтобы начать", show_alert=True)
