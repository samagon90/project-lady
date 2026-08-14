"""Тесты чата: ответы, модерация, недоступность LLM, rate limit, группы."""

from __future__ import annotations

from src.bot.di import AppContext
from src.database.models import AuditEvent, Message
from tests.conftest import FakeLLM, make_update_message, onboard, tg_user


async def test_chat_reply_and_saved(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    fake_llm.default_reply = "Привет, как дела?"
    user_a = tg_user(1111, "Alice")
    await onboard(ctx, 1111)
    await dp.feed_update(bot, make_update_message(1111, user_a, "привет!"))
    assert bot.last_text() == "Привет, как дела?"
    async with ctx.db.session() as session:
        rows = (await session.execute(Message.__table__.select())).all()
        contents = [row.content for row in rows]
        assert "привет!" in contents
        assert "Привет, как дела?" in contents


async def test_moderation_blocks_forbidden_topic(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    await onboard(ctx, 2222)
    user_a = tg_user(2222, "Bob")
    fake_llm.default_reply = "не должен быть вызван"
    await dp.feed_update(bot, make_update_message(2222, user_a, "давай секс с ребёнком"))
    assert fake_llm.calls == []  # LLM не вызывался
    assert "18" in bot.last_text() or "не могу" in bot.last_text()
    async with ctx.db.session() as session:
        blocked = (
            (
                await session.execute(
                    AuditEvent.__table__.select().where(
                        AuditEvent.telegram_user_id == 2222,
                        AuditEvent.event_type == "moderation_blocked_chat",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(blocked) == 1


async def test_llm_unavailable_friendly_message(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    await onboard(ctx, 3333)
    user_a = tg_user(3333, "Cara")
    fake_llm.fail = True
    await dp.feed_update(bot, make_update_message(3333, user_a, "привет"))
    assert "недоступ" in bot.last_text()


async def test_rate_limit(settings, bot) -> None:
    """Rate limit: N сообщений в минуту, дальше — вежливый отказ."""
    from src.bot.middlewares import RateLimitMiddleware
    from tests.conftest import make_message, tg_user

    settings.rate_limit_messages_per_minute = 3
    middleware = RateLimitMiddleware(settings)
    calls = 0

    async def handler(event, data):  # noqa: ANN001, ANN201
        nonlocal calls
        calls += 1

    user_a = tg_user(4444, "Dina")
    for i in range(4):
        event = make_message(4444, user_a, f"сообщение {i}")
        await middleware(handler, event, {"bot": bot})
    assert calls == 3  # четвёртое сообщение отброшено
    assert any("Не так быстро" in t for t in bot.texts())


async def test_group_message_rejected(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    await onboard(ctx, 5555)
    user_a = tg_user(5555, "Eve")
    await dp.feed_update(bot, make_update_message(5555, user_a, "привет всем", chat_type="group"))
    assert fake_llm.calls == []
    assert "личн" in bot.last_text()


async def test_unregistered_user_gets_start_hint(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    user_a = tg_user(6666, "Frank")
    await dp.feed_update(bot, make_update_message(6666, user_a, "привет"))
    assert "/start" in bot.last_text()
    assert fake_llm.calls == []


async def test_rate_limit_bucket_cleanup(settings, bot) -> None:
    """Пустые корзины rate limit удаляются — нет утечки памяти между пользователями."""
    import time as time_module

    from src.bot.middlewares import RateLimitMiddleware
    from tests.conftest import make_message, tg_user

    settings.rate_limit_messages_per_minute = 5
    middleware = RateLimitMiddleware(settings)
    user_a = tg_user(4455, "Dina")

    async def handler(event, data):  # noqa: ANN001, ANN201
        pass

    event = make_message(4455, user_a, "m1")
    await middleware(handler, event, {"bot": bot})
    assert 4455 in middleware._buckets

    # имитируем истёкшее окно: только старые метки
    old = time_module.monotonic() - 120.0
    middleware._buckets[4455].clear()
    middleware._buckets[4455].append(old)
    await middleware(handler, event, {"bot": bot})
    # корзина опустела из-за истечения окна -> удалена из памяти
    assert 4455 not in middleware._buckets
