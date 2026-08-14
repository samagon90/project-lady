"""Тесты онбординга: age gate, согласия, режимы."""

from __future__ import annotations

from aiogram import Dispatcher

from src.bot.di import AppContext
from src.database.repositories import ConsentRepository, PreferencesRepository, UserRepository
from tests.conftest import (
    make_callback,
    make_update_callback,
    make_update_message,
    onboard,
    tg_user,
)


async def test_registration_via_start(dp: Dispatcher, bot, ctx: AppContext) -> None:
    user_a = tg_user(111, "Alice")
    # /start без пользователя -> age gate
    await dp.feed_update(bot, make_update_message(111, user_a, "/start"))
    assert "18" in bot.last_text()
    assert "ИИ" in bot.last_text()

    # age gate -> политика согласия
    await dp.feed_update(bot, make_update_callback(make_callback(111, user_a, "age:ok")))
    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(111)
        assert user is not None
        assert user.consent_step == "base_pending"
    assert "ПОЛИТИКА" in bot.last_text() or "политик" in bot.last_text().lower()

    # базовая политика -> вопрос про NSFW
    await dp.feed_update(bot, make_update_callback(make_callback(111, user_a, "consent:base:ok")))
    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(111)
        consent = await ConsentRepository(session).get_active(user.id, "base")
        assert consent is not None
        assert consent.version
    assert "NSFW" in bot.last_text()

    # NSFW-согласие -> активный пользователь
    await dp.feed_update(bot, make_update_callback(make_callback(111, user_a, "consent:nsfw:ok")))
    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(111)
        assert user.consent_step == "active"
        nsfw = await ConsentRepository(session).get_active(user.id, "nsfw")
        assert nsfw is not None
        prefs = await PreferencesRepository(session).get_or_create(user)
        assert prefs.mode == 0  # NSFW-режим не включается автоматически


async def test_age_gate_exit_creates_no_user(dp: Dispatcher, bot, ctx: AppContext) -> None:
    user = tg_user(222, "Bob")
    await dp.feed_update(bot, make_update_message(222, user, "/start"))
    await dp.feed_update(bot, make_update_callback(make_callback(222, user, "age:exit")))
    async with ctx.db.session() as session:
        db_user = await UserRepository(session).get_by_telegram_id(222)
        assert db_user is None


async def test_nsfw_impossible_before_consent(dp: Dispatcher, bot, ctx: AppContext) -> None:
    user_a = tg_user(333, "Cara")
    await onboard(ctx, 333, nsfw=False)  # без NSFW-согласия
    await dp.feed_update(bot, make_update_message(333, user_a, "/mode"))
    await dp.feed_update(bot, make_update_callback(make_callback(333, user_a, "mode:set:3")))
    async with ctx.db.session() as session:
        db_user = await UserRepository(session).get_by_telegram_id(333)
        prefs = await PreferencesRepository(session).get_or_create(db_user)
        assert prefs.mode != 3
    # пользователю показано предложение согласия
    assert any("согласи" in text for text in bot.texts())


async def test_nsfw_opt_out_revokes_consent(ctx: AppContext) -> None:
    user = await onboard(ctx, 444, nsfw=True)
    async with ctx.db.session() as session:
        prefs = await PreferencesRepository(session).update_fields(user, mode=3)
        assert prefs.mode == 3
        assert await ConsentRepository(session).get_active(user.id, "nsfw") is not None
    await ctx.consent.revoke_nsfw(user)
    async with ctx.db.session() as session:
        assert await ConsentRepository(session).get_active(user.id, "nsfw") is None
        prefs = await PreferencesRepository(session).get_or_create(user)
        assert prefs.mode == 2  # режим сброшен с NSFW на романтический


async def test_mode_switching(dp: Dispatcher, bot, ctx: AppContext) -> None:
    user_a = tg_user(555, "Dina")
    await onboard(ctx, 555, nsfw=True)
    for mode, expected in ((2, 2), (1, 1), (0, 0), (3, 3)):
        await dp.feed_update(bot, make_update_callback(make_callback(555, user_a, f"mode:set:{mode}")))
        async with ctx.db.session() as session:
            db_user = await UserRepository(session).get_by_telegram_id(555)
            prefs = await PreferencesRepository(session).get_or_create(db_user)
            assert prefs.mode == expected, f"mode {mode}"

    async with ctx.db.session() as session:
        from src.database.models import AuditEvent

        db_user = await UserRepository(session).get_by_telegram_id(555)
        assert db_user is not None
        events = (
            (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.telegram_user_id == 555, AuditEvent.event_type == "mode_changed"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 4
