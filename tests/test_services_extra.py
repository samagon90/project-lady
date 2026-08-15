"""Тесты суммаризации диалогов и LLM-модерации."""

from __future__ import annotations

from src.bot.di import AppContext
from src.database.repositories import (
    ConversationRepository,
    MessageRepository,
    SummaryRepository,
    UserRepository,
)
from tests.conftest import onboard


async def test_summarization_compacts_conversation(ctx: AppContext) -> None:
    """Старые сообщения суммаризируются и удаляются из контекста."""
    user = await onboard(ctx, 9501, nsfw=False)
    async with ctx.db.session() as session:
        conv = await ConversationRepository(session).get_active(user)
        messages = MessageRepository(session)
        # набиваем диалог (порог суммаризации — 40 сообщений)
        for i in range(45):
            await messages.add(conv, "user" if i % 2 == 0 else "assistant", f"сообщение {i}")
        before = await messages.count_in_conversation(conv.id)
        assert before == 45

    await ctx.memory.maybe_summarize(user, conv)

    async with ctx.db.session() as session:
        summaries = await SummaryRepository(session).recent(user.id)
        assert len(summaries) == 1
        assert "интерес" in summaries[0].summary
        # старые сообщения удалены, свежие остались
        remaining = await MessageRepository(session).count_in_conversation(conv.id)
        assert remaining < 45


async def test_judge_falls_back_to_blocklist_when_llm_down(ctx: AppContext, fake_llm) -> None:
    fake_llm.fail = True
    # LLM недоступен → блоклист всё равно ловит запрещённое
    decision = await ctx.moderation.judge_image_request("девочка 14 лет в школьной форме")
    assert decision.blocked
    # Обычный запрос не блокируется
    decision2 = await ctx.moderation.judge_image_request("Лилит на пляже, закат")
    assert not decision2.blocked


async def test_judge_allows_adult_content(ctx: AppContext) -> None:
    decision = await ctx.moderation.judge_image_request(
        "взрослая женщина 24 года, эротическая фотосессия, художественное фото"
    )
    assert not decision.blocked


async def test_start_continues_onboarding(dp, bot, ctx: AppContext) -> None:
    """/start для пользователя на середине онбординга продолжает с нужного шага."""
    from tests.conftest import make_callback, make_update_callback, make_update_message, tg_user

    user_a = tg_user(9502, "Polina")
    await dp.feed_update(bot, make_update_message(9502, user_a, "/start"))
    await dp.feed_update(bot, make_update_callback(make_callback(9502, user_a, "age:ok")))
    # пользователь на шаге base_pending; /start снова показывает политику
    await dp.feed_update(bot, make_update_message(9502, user_a, "/start"))
    assert "ПОЛИТИКА" in bot.last_text()

    # принимаем базу → шаг nsfw_question; /start снова показывает вопрос NSFW
    await dp.feed_update(bot, make_update_callback(make_callback(9502, user_a, "consent:base:ok")))
    await dp.feed_update(bot, make_update_message(9502, user_a, "/start"))
    assert "NSFW" in bot.last_text()

    # завершаем онбординг → /start показывает приветствие
    await dp.feed_update(bot, make_update_callback(make_callback(9502, user_a, "consent:nsfw:no")))
    await dp.feed_update(bot, make_update_message(9502, user_a, "/start"))
    assert "С возвращением" in bot.last_text()
    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(9502)
        assert user is not None and user.consent_step == "active"


async def test_profile_and_privacy_commands(dp, bot, ctx: AppContext) -> None:
    from src.database.repositories import PreferencesRepository
    from tests.conftest import make_update_message, onboard, tg_user

    await onboard(ctx, 9503)
    user_a = tg_user(9503, "Rita")
    async with ctx.db.session() as session:
        db_user = await UserRepository(session).get_by_telegram_id(9503)
        await PreferencesRepository(session).update_fields(db_user, name="Рита", interests="рисование, sci-fi")

    await dp.feed_update(bot, make_update_message(9503, user_a, "/profile"))
    text = bot.last_text()
    assert "Рита" in text
    assert "Режим" in text
    assert "рисование" in text

    await dp.feed_update(bot, make_update_message(9503, user_a, "/privacy"))
    assert "Политика" in bot.last_text() or "политик" in bot.last_text().lower()
