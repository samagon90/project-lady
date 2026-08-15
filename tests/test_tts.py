"""Тесты голосовых сообщений: отправка voice, fallback при недоступности TTS."""

from __future__ import annotations

from src.bot.di import AppContext
from src.database.repositories import UserRepository
from tests.conftest import FakeTTS, make_update_message, onboard, tg_user


async def _set_voice(ctx: AppContext, uid: int, enabled: bool) -> None:
    async with ctx.db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(uid)
        from src.database.repositories import PreferencesRepository

        await PreferencesRepository(session).update_fields(user, voice_enabled=enabled)


async def test_voice_message_sent(ctx: AppContext, dp, bot, fake_llm) -> None:
    await onboard(ctx, 8101)
    user_a = tg_user(8101, "Kira")
    await _set_voice(ctx, 8101, True)
    await dp.feed_update(bot, make_update_message(8101, user_a, "расскажи о себе"))
    assert any(item[0] == "photo" for item in bot.sent)
    assert any(item[0] == "voice" for item in bot.sent), "voice должен быть отправлен"
    # временный ogg удалён после отправки
    remaining = list(ctx.storage.temp_dir.glob("voice_*.ogg"))
    assert remaining == []


async def test_voice_off_sends_text_only(ctx: AppContext, dp, bot, fake_llm) -> None:
    await onboard(ctx, 8102)
    user_a = tg_user(8102, "Leo")
    await _set_voice(ctx, 8102, False)
    await dp.feed_update(bot, make_update_message(8102, user_a, "привет"))
    # ответ приходит как фото с подписью (текст в caption)
    assert any(item[0] == "photo" for item in bot.sent)
    assert not any(item[0] == "voice" for item in bot.sent)


async def test_tts_fallback_text_still_sent(ctx: AppContext, dp, bot, fake_llm, fake_tts: FakeTTS) -> None:
    await onboard(ctx, 8103)
    user_a = tg_user(8103, "Mia")
    await _set_voice(ctx, 8103, True)
    fake_tts.fail = True  # Piper недоступен
    await dp.feed_update(bot, make_update_message(8103, user_a, "привет!"))
    # текст отправлен (в подписи фото), голосовое пропущено без падения
    assert any(item[0] == "photo" for item in bot.sent)
    assert not any(item[0] == "voice" for item in bot.sent)
