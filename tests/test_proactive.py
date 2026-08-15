"""Тесты проактивных сообщений: Лилит сама пишет молчащим пользователям."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update

from src.database.models import User
from src.database.repositories import AuditRepository, UserRepository
from src.utils import utcnow
from src.workers import ProactiveWorker
from tests.conftest import FakeBot, onboard


async def _make_inactive(ctx, uid: int, hours_ago: int = 24, *, nsfw: bool = True):
    user = await onboard(ctx, uid, nsfw=nsfw)
    async with ctx.db.session() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(last_active_at=utcnow() - timedelta(hours=hours_ago))
        )
    return user


async def test_proactive_sends_to_inactive_user(ctx, fake_llm) -> None:
    fake_llm.fail = True  # LLM недоступна -> запасная фраза
    await _make_inactive(ctx, 9601, hours_ago=24)
    bot = FakeBot()
    worker = ProactiveWorker(ctx, bot, ctx.stop_event)
    await worker.proactive_once()
    sent = [item for item in bot.sent if item[0] == "message" and item[1] == 9601]
    assert sent, "молчащему пользователю должно прийти сообщение"
    # событие аудита записано
    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(9601)
        assert await AuditRepository(session).last_event_time(user.id, "proactive_sent") is not None


async def test_proactive_not_sent_to_recently_active(ctx, fake_llm) -> None:
    fake_llm.fail = True
    await _make_inactive(ctx, 9602, hours_ago=1)  # был активен час назад
    bot = FakeBot()
    worker = ProactiveWorker(ctx, bot, ctx.stop_event)
    await worker.proactive_once()
    assert not any(item[1] == 9602 for item in bot.sent)


async def test_proactive_respects_daily_limit(ctx, fake_llm, settings) -> None:
    fake_llm.fail = True
    settings.proactive_max_per_day = 2
    user = await _make_inactive(ctx, 9603, hours_ago=24)
    # уже отправлено 2 сообщения сегодня
    async with ctx.db.session() as session:
        audit = AuditRepository(session)
        for _ in range(2):
            await audit.add("proactive_sent", user=user)
    bot = FakeBot()
    worker = ProactiveWorker(ctx, bot, ctx.stop_event)
    await worker.proactive_once()
    assert not any(item[1] == 9603 for item in bot.sent)


async def test_proactive_not_sent_to_blocked_or_unfinished(ctx, fake_llm) -> None:
    fake_llm.fail = True
    await _make_inactive(ctx, 9604, hours_ago=24)
    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(9604)
        user.is_blocked = True
    bot = FakeBot()
    worker = ProactiveWorker(ctx, bot, ctx.stop_event)
    await worker.proactive_once()
    assert not any(item[1] == 9604 for item in bot.sent)


async def test_proactive_uses_llm_when_available(ctx, fake_llm) -> None:
    fake_llm.default_reply = "Мой дорогой, я заждалась… Заходи скорее."
    await _make_inactive(ctx, 9605, hours_ago=24)
    bot = FakeBot()
    worker = ProactiveWorker(ctx, bot, ctx.stop_event)
    await worker.proactive_once()
    sent = [item for item in bot.sent if item[1] == 9605]
    assert sent
    text = sent[0][2]["text"]
    assert "дорог" in text
