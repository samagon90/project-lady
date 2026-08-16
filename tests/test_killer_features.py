"""Тесты киллер-фич v1.8.9: уровни/XP, свайпы, лорбук, дневник, Mini App."""

from __future__ import annotations

from src.bot.di import AppContext
from src.database.repositories import DiaryRepository, PreferencesRepository
from src.prompts import lorebook_for_query, parse_lorebook
from src.services.chat import (
    RELATIONSHIP_LEVELS,
    level_for_xp,
    level_name,
    level_progress,
)
from tests.conftest import FakeLLM, make_update_message, onboard, tg_user

# ---------------------------------------------------------------------------
# Уровни отношений и XP (фича Replika)
# ---------------------------------------------------------------------------


def test_levels_basic() -> None:
    assert level_for_xp(0) == 1
    assert level_for_xp(49) == 1
    assert level_for_xp(50) == 2
    assert level_for_xp(149) == 2
    assert level_for_xp(150) == 3
    assert level_for_xp(300) == 4
    assert level_for_xp(500) == 5
    assert level_for_xp(800) == 6
    assert level_for_xp(10_000) == 7
    assert level_name(1) == "Знакомство"
    assert level_name(7) == "Родные души"
    assert len(RELATIONSHIP_LEVELS) == 7


def test_level_progress() -> None:
    level, xp_to_next, progress = level_progress(25)
    assert level == 1
    assert xp_to_next == 25
    assert 0.0 < progress < 1.0
    # Максимальный уровень: прогресс 100%, до следующего 0
    level, xp_to_next, progress = level_progress(10_000)
    assert level == 7
    assert xp_to_next == 0
    assert progress == 1.0


async def test_chat_awards_xp(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    """Каждое сообщение даёт XP; ChatResult возвращает уровень."""
    await onboard(ctx, 7001)
    user_a = tg_user(7001, "Alice")
    fake_llm.default_reply = "Привет, солнышко!"
    await dp.feed_update(bot, make_update_message(7001, user_a, "привет"))
    async with ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(await _user(ctx, 7001))
        assert (prefs.xp or 0) >= 3
        assert level_for_xp(prefs.xp or 0) >= 1


async def test_level_up_at_threshold(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    """При пересечении порога (50 XP) — сообщение о повышении уровня."""
    await onboard(ctx, 7002)
    user = await _user(ctx, 7002)
    # Ставим 49 XP — одно сообщение даст 3+ XP и пересечёт порог
    async with ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(user, xp=49)
    fake_llm.default_reply = "Привет!"
    await dp.feed_update(bot, make_update_message(7002, tg_user(7002, "Bob"), "привет"))
    all_texts = " ".join(bot.texts())
    assert "уровень" in all_texts.lower()


async def test_alternatives(ctx: AppContext, fake_llm: FakeLLM) -> None:
    """Свайпы: возвращает несколько разных вариантов ответа."""
    await onboard(ctx, 7003)
    user = await _user(ctx, 7003)
    fake_llm.default_reply = "Вариант ответа от модели"
    # Сначала обычное сообщение (чтобы был контекст)
    from src.database.repositories import ConversationRepository, MessageRepository

    async with ctx.db.session() as session:
        conversation = await ConversationRepository(session).get_active(user)
        await MessageRepository(session).add(conversation, "user", "расскажи о себе")
    variants = await ctx.chat.alternatives(user, "расскажи о себе", n=2)
    assert len(variants) >= 1
    assert all(isinstance(v, str) and v for v in variants)


# ---------------------------------------------------------------------------
# Лорбук (фича SillyTavern / HammerAI)
# ---------------------------------------------------------------------------


def test_parse_lorebook() -> None:
    raw = """# Книга мира

## Запись: Дом
Триггеры: дом, квартира
Текст: Я живу в старой квартире.

## Запись: Кот
Триггеры: кот, кошка
Текст: У меня живёт чёрный кот Барон.
"""
    entries = parse_lorebook(raw)
    assert len(entries) == 2
    assert entries[0]["title"] == "Дом"
    assert "квартире" in entries[0]["text"]
    assert entries[0]["triggers"] == "дом, квартира"


def test_lorebook_for_query() -> None:
    raw = """## Запись: Кот
Триггеры: кот, кошка, питомец
Текст: У меня живёт чёрный кот Барон.
"""
    entries = parse_lorebook(raw)
    hits = lorebook_for_query(entries, "расскажи про своего кота")
    assert len(hits) == 1
    assert "Барон" in hits[0]["text"]
    # Триггер не упомянут — запись не подмешивается
    assert lorebook_for_query(entries, "как дела?") == []


def test_lorebook_loaded_from_project() -> None:
    from src.prompts import PromptLibrary

    lib = PromptLibrary()
    assert len(lib.lorebook_entries) >= 5, "в lorebook.md должно быть не менее 5 записей"
    assert lorebook_for_query(lib.lorebook_entries, "где ты живёшь?")
    assert lorebook_for_query(lib.lorebook_entries, "как тебя зовут?") == []


async def test_lorebook_in_context(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    """Запись лорбука попадает в контекст LLM, когда пользователь
    упоминает триггер (например, «кот»)."""
    await onboard(ctx, 7004)
    fake_llm.default_reply = "Привет!"
    await dp.feed_update(bot, make_update_message(7004, tg_user(7004, "Cara"), "расскажи про своего кота"))
    # В последнем вызове LLM должен быть текст про Барона
    joined = "\n".join(str(m) for call in fake_llm.calls for m in call)
    assert "Барон" in joined


# ---------------------------------------------------------------------------
# Дневник Лилит (фича Replika)
# ---------------------------------------------------------------------------


async def test_diary_repository(ctx: AppContext) -> None:
    await onboard(ctx, 7005)
    user = await _user(ctx, 7005)
    async with ctx.db.session() as session:
        diary = DiaryRepository(session)
        assert not await diary.has_entry_for_date(user.id, "2026-08-16")
        await diary.add(user, "2026-08-16", "Сегодня был чудесный день.")
        assert await diary.has_entry_for_date(user.id, "2026-08-16")
        entries = await diary.list_recent(user.id)
        assert len(entries) == 1
        assert entries[0].text == "Сегодня был чудесный день."
    # Изоляция по пользователям (сессия закрыта — иначе SQLite «locked»)
    await onboard(ctx, 7006)
    user2 = await _user(ctx, 7006)
    async with ctx.db.session() as session:
        diary = DiaryRepository(session)
        assert not await diary.has_entry_for_date(user2.id, "2026-08-16")


# ---------------------------------------------------------------------------
# Mini App: новые эндпоинты
# ---------------------------------------------------------------------------


async def test_miniapp_me_returns_level(ctx: AppContext) -> None:
    import hashlib
    import hmac
    import json as _json
    import urllib.parse

    from src.miniapp_server import MiniAppServer

    token = "123:TESTTOKEN"
    await onboard(ctx, 7007)
    server = MiniAppServer(ctx.db, token)

    user = _json.dumps({"id": 7007, "first_name": "T", "is_bot": False})
    pairs = [("user", user), ("auth_date", "1700000000")]
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    init = urllib.parse.urlencode(pairs + [("hash", digest)])

    class _Req:
        headers = {"x-init-data": init}

        async def json(self):
            return {}

    resp = await server._api_me(_Req())
    assert resp.status == 200, resp.body
    data = _json.loads(resp.body)
    assert "level" in data and "level_name" in data and "xp" in data
    assert data["level"] >= 1
    assert data["level_name"] == "Знакомство"


async def test_miniapp_diary_endpoint(ctx: AppContext) -> None:
    import hashlib
    import hmac
    import json as _json
    import urllib.parse

    from src.miniapp_server import MiniAppServer

    token = "123:TESTTOKEN"
    await onboard(ctx, 7008)
    user = await _user(ctx, 7008)
    async with ctx.db.session() as session:
        await DiaryRepository(session).add(user, "2026-08-16", "Запись из дневника.")
    server = MiniAppServer(ctx.db, token)

    user_json = _json.dumps({"id": 7008, "first_name": "T", "is_bot": False})
    pairs = [("user", user_json), ("auth_date", "1700000000")]
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    init = urllib.parse.urlencode(pairs + [("hash", digest)])

    class _Req:
        headers = {"x-init-data": init}

        async def json(self):
            return {}

    resp = await server._api_diary(_Req())
    assert resp.status == 200, resp.body
    data = _json.loads(resp.body)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["text"] == "Запись из дневника."


async def test_miniapp_settings_creativity(ctx: AppContext) -> None:
    """Настройки креативности/длины сохраняются через Mini App API."""
    import hashlib
    import hmac
    import json as _json
    import urllib.parse

    from src.database.repositories import PreferencesRepository, UserRepository
    from src.miniapp_server import MiniAppServer

    token = "123:TESTTOKEN"
    await onboard(ctx, 7009)
    server = MiniAppServer(ctx.db, token)

    user_json = _json.dumps({"id": 7009, "first_name": "T", "is_bot": False})
    pairs = [("user", user_json), ("auth_date", "1700000000")]
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    init = urllib.parse.urlencode(pairs + [("hash", digest)])

    class _Req:
        headers = {"x-init-data": init}

        def __init__(self, body):
            self._body = body

        async def json(self):
            return _json.loads(self._body)

    resp = await server._api_settings(_Req(_json.dumps({"creativity": 2, "response_length": 0})))
    assert resp.status == 200, resp.body
    async with ctx.db.session() as session:
        u = await UserRepository(session).get_by_telegram_id(7009)
        prefs = await PreferencesRepository(session).get_or_create(u)
        assert prefs.creativity == 2
        assert prefs.response_length == 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _user(ctx: AppContext, tg_id: int):
    from src.database.repositories import UserRepository

    async with ctx.db.session() as session:
        return await UserRepository(session).get_by_telegram_id(tg_id)


# ---------------------------------------------------------------------------
# v2.0: стрики (серия дней) и достижения
# ---------------------------------------------------------------------------


async def test_streak_first_message(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    """Первое сообщение сегодня — стрик = 1."""
    await onboard(ctx, 8001)
    fake_llm.default_reply = "Привет!"
    await dp.feed_update(bot, make_update_message(8001, tg_user(8001, "A"), "привет"))
    async with ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(await _user(ctx, 8001))
        assert prefs.streak == 1
        assert prefs.max_streak == 1
        assert prefs.last_active_date is not None


async def test_streak_continues_next_day(ctx: AppContext) -> None:
    """Если вчера был диалог, а сегодня новый — стрик растёт."""
    from datetime import timedelta

    from src.utils import utcnow

    await onboard(ctx, 8002)
    user = await _user(ctx, 8002)
    yesterday = (utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    async with ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(
            user, streak=5, max_streak=5, last_active_date=yesterday
        )
    streak, text = await ctx.chat._update_streak(user)
    assert streak == 6
    assert text is None  # 6 — не юбилей
    async with ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
        assert prefs.max_streak == 6


async def test_streak_week_milestone_text(ctx: AppContext) -> None:
    """7-й день подряд — поздравление."""
    from datetime import timedelta

    from src.utils import utcnow

    await onboard(ctx, 8003)
    user = await _user(ctx, 8003)
    yesterday = (utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    async with ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(
            user, streak=6, last_active_date=yesterday
        )
    _streak, text = await ctx.chat._update_streak(user)
    assert text is not None
    assert "Неделя" in text or "неделя" in text


async def test_streak_broken_after_gap(ctx: AppContext) -> None:
    """Пропуск дня сбрасывает стрик на 1."""
    from datetime import timedelta

    from src.utils import utcnow

    await onboard(ctx, 8004)
    user = await _user(ctx, 8004)
    three_days_ago = (utcnow() - timedelta(days=3)).strftime("%Y-%m-%d")
    async with ctx.db.session() as session:
        await PreferencesRepository(session).update_fields(
            user, streak=10, max_streak=10, last_active_date=three_days_ago
        )
    streak, _text = await ctx.chat._update_streak(user)
    assert streak == 1  # серия сброшена, но рекорд остался
    async with ctx.db.session() as session:
        prefs = await PreferencesRepository(session).get_or_create(user)
        assert prefs.max_streak == 10


async def test_first_message_achievement(ctx: AppContext, dp, bot, fake_llm: FakeLLM) -> None:
    """Первое сообщение выдаёт достижение «Первое слово»."""
    await onboard(ctx, 8005)
    fake_llm.default_reply = "Привет, дорогой!"
    await dp.feed_update(bot, make_update_message(8005, tg_user(8005, "B"), "привет"))
    all_texts = " ".join(bot.texts())
    assert "Первое слово" in all_texts or "достижение" in all_texts.lower()
    async with ctx.db.session() as session:
        from src.database.repositories import AchievementRepository

        ach = await AchievementRepository(session).list_for_user((await _user(ctx, 8005)).id)
        codes = [a.code for a in ach]
        assert "first_message" in codes
