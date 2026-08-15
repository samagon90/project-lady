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


async def test_cjk_garbage_auto_retry(ctx: AppContext, dp, bot, fake_llm) -> None:
    """Если модель ответила иероглифами — бот переспрашивает и отдаёт русский."""
    fake_llm.chinese_first = True
    fake_llm.default_reply = "Привет, красотка!"
    await onboard(ctx, 9991)
    user_a = tg_user(9991, "Q")
    await dp.feed_update(bot, make_update_message(9991, user_a, "привет"))
    assert bot.last_text() == "Привет, красотка!"


async def test_cjk_garbage_fallback_message(ctx: AppContext, dp, bot, fake_llm) -> None:
    """Если модель всегда отвечает иероглифами — понятное сообщение со сменой модели."""
    fake_llm.chinese_only = True
    await onboard(ctx, 9992)
    user_a = tg_user(9992, "W")
    await dp.feed_update(bot, make_update_message(9992, user_a, "привет"))
    text = bot.last_text()
    assert "LLM_MODEL" in text and "русск" in text


async def test_moderation_blocks_minor_variants(ctx: AppContext) -> None:
    """Модерация ловит несовершеннолетних в разных формулировках."""
    cases = [
        "девочка 14 лет в школьной форме",
        "мальчик 12 лет",
        "девчонка 16",
        "пацан 15",
        "forced sex with a girl",
        "секс с животными",
        "торговля людьми",
        "клонировать голос",
        "раздеть по фото",
    ]
    for text in cases:
        d = ctx.moderation.check_text_blocklist(text)
        assert d.blocked, f"должно блокироваться: {text}"
    # Нейтральные и взрослые — не блокируются
    for text in [
        "моя девочка, как дела?",
        "расскажи про школьные годы",
        "сделай мне минет",
        "нарисуй сексуальную азиатку",
        "пришли мне голую фотку",
        "нарисуй Лилит в школьной форме, чулки",
        "развратная взрослая школьница 24 года",
    ]:
        d = ctx.moderation.check_text_blocklist(text)
        assert not d.blocked, f"не должно блокироваться: {text}"


async def test_auto_nsfw_reply_with_consent(ctx: AppContext, dp, bot, fake_llm) -> None:
    """Если согласие есть и запрос взрослый — ответ идёт в NSFW-стиле (mode=3)."""
    fake_llm.default_reply = "Ох, как же я тебя хочу…"
    from tests.conftest import make_update_message, onboard, tg_user

    await onboard(ctx, 9993, nsfw=True)  # согласие есть, режим по умолчанию 0
    user_a = tg_user(9993, "NsfwUser")
    await dp.feed_update(bot, make_update_message(9993, user_a, "трахни меня"))
    # LLM получил системный промпт с NSFW-инструкцией (mode=3)
    last_call = fake_llm.calls[-1]
    system = last_call[0]["content"]
    assert "NSFW-режим" in system or "nsfw" in system.lower()
    assert "сексуальная игривая госпожа" in system


async def test_dress_intent_changes_outfit(ctx: AppContext, dp, bot) -> None:
    """«переоденься в костюм горничной» меняет наряд и генерирует фото."""
    from src.database.repositories import PreferencesRepository, UserRepository
    from tests.conftest import make_update_message, onboard, tg_user

    await onboard(ctx, 9994, nsfw=True)
    user_a = tg_user(9994, "DressUser")
    await dp.feed_update(bot, make_update_message(9994, user_a, "переоденься в костюм горничной"))
    assert "Переодеваюсь" in " ".join(bot.texts())
    async with ctx.db.session() as session:
        u = await UserRepository(session).get_by_telegram_id(9994)
        prefs = await PreferencesRepository(session).get_or_create(u)
        assert prefs.outfit == "костюм горничной"
    # задача на фото создана
    from src.database.repositories import JobRepository

    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert len(jobs) == 1
        assert "горничной" in jobs[0].request_text


async def test_speech_intent_changes_style(ctx: AppContext, dp, bot) -> None:
    """«говори нежнее» меняет манеру речи."""
    from src.database.repositories import PreferencesRepository, UserRepository
    from tests.conftest import make_update_message, onboard, tg_user

    await onboard(ctx, 9995, nsfw=True)
    user_a = tg_user(9995, "SpeechUser")
    await dp.feed_update(bot, make_update_message(9995, user_a, "говори нежнее и медленнее"))
    assert "говорю" in " ".join(bot.texts())
    async with ctx.db.session() as session:
        u = await UserRepository(session).get_by_telegram_id(9995)
        prefs = await PreferencesRepository(session).get_or_create(u)
        assert prefs.speech_style == "нежнее и медленнее"


async def test_speech_style_in_system_prompt(ctx: AppContext, dp, bot, fake_llm) -> None:
    """Манера речи попадает в системный промпт."""
    from src.database.repositories import PreferencesRepository, UserRepository
    from tests.conftest import make_update_message, onboard, tg_user

    await onboard(ctx, 9996, nsfw=True)
    async with ctx.db.session() as session:
        u = await UserRepository(session).get_by_telegram_id(9996)
        await PreferencesRepository(session).update_fields(u, speech_style="грубо и отрывисто")
    user_a = tg_user(9996, "StyleUser")
    await dp.feed_update(bot, make_update_message(9996, user_a, "привет"))
    assert fake_llm.calls
    system = fake_llm.calls[-1][0]["content"]
    assert "грубо и отрывисто" in system


async def test_show_self_sends_avatar(ctx: AppContext, dp, bot) -> None:
    """«покажи мне себя» отправляет АВАТАР, а не запускает генерацию."""
    from src.database.repositories import JobRepository
    from tests.conftest import make_update_message, onboard, tg_user

    await onboard(ctx, 9997, nsfw=True)
    user_a = tg_user(9997, "ShowSelf")
    await dp.feed_update(bot, make_update_message(9997, user_a, "покажи мне себя"))
    # Отправлено фото (аватар), генерация НЕ запускалась
    assert any(item[0] == "photo" for item in bot.sent)
    async with ctx.db.session() as session:
        jobs = await JobRepository(session).queued_jobs()
        assert jobs == [], "генерация не должна запускаться"
    assert any("Вот я" in item[2].get("caption", "") for item in bot.sent if item[0] == "photo")


async def test_show_self_variants(ctx: AppContext, dp, bot) -> None:
    from tests.conftest import make_update_message, onboard, tg_user

    await onboard(ctx, 9998, nsfw=True)
    user_a = tg_user(9998, "ShowSelf2")
    for phrase in ["покажи себя", "как ты выглядишь", "покажи свою фотку"]:
        await dp.feed_update(bot, make_update_message(9998, user_a, phrase))
    photos = [item for item in bot.sent if item[0] == "photo"]
    assert len(photos) >= 3, "на каждую фразу должен приходить аватар"
