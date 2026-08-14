"""Тесты /forget_me: полное каскадное удаление."""

from __future__ import annotations

from sqlalchemy import func, select

from src.bot.di import AppContext
from src.database.models import (
    AuditEvent,
    Conversation,
    ConversationSummary,
    GeneratedAsset,
    GenerationJob,
    MemoryItem,
    Message,
    UserConsent,
    UserPreferences,
)
from src.database.repositories import UserRepository
from tests.conftest import drain_background, onboard

ALL_TABLES = [
    UserConsent,
    UserPreferences,
    Conversation,
    Message,
    MemoryItem,
    ConversationSummary,
    GenerationJob,
    GeneratedAsset,
    AuditEvent,
]


async def test_forget_me_deletes_everything(ctx: AppContext) -> None:
    user_a = await onboard(ctx, 7001, nsfw=True)
    await onboard(ctx, 7002, nsfw=True)

    # A: диалог + память + ассет-файл
    ctx.chat.llm.extraction_facts = [
        {
            "category": "profile",
            "fact": "Тайна пользователя A",
            "confidence": 0.9,
            "sensitivity": "low",
            "expires_at": None,
        }
    ]
    await ctx.chat.handle_message(user_a, "мой секрет: я коллекционирую кактусы", 1)
    await drain_background(ctx)

    asset_file = ctx.storage.new_temp_path("img", ".png")
    asset_file.write_bytes(b"PNG")
    async with ctx.db.session() as session:
        from src.database.repositories import AssetRepository

        await AssetRepository(session).add(
            user_a,
            asset_type="image",
            file_path=str(asset_file),
            mime_type="image/png",
            size_bytes=4,
            job_id=None,
        )

    assert asset_file.exists()

    # Удаляем пользователя A
    await ctx.delete_user_data(user_a)

    # 1. Файлы удалены
    assert not asset_file.exists()

    # 2. Все таблицы пусты для A
    async with ctx.db.session() as session:
        for table in ALL_TABLES:
            count = await session.execute(select(func.count()).select_from(table).where(table.telegram_user_id == 7001))
            assert int(count.scalar_one()) == 0, f"таблица {table.__tablename__} не очищена"
        assert await UserRepository(session).get_by_telegram_id(7001) is None

        # 3. B не задет
        assert await UserRepository(session).get_by_telegram_id(7002) is not None

    # 4. Векторный индекс не содержит памяти A
    assert all(owner != 7001 for owner in ctx.embeddings.store._owners.values())


async def test_forget_me_via_callback(dp, bot, ctx: AppContext) -> None:
    from tests.conftest import make_callback, make_update_callback, make_update_message, tg_user

    user_a = tg_user(7003, "Gina")
    await onboard(ctx, 7003)
    await dp.feed_update(bot, make_update_message(7003, user_a, "/forget_me"))
    assert any("необратимо" in t for t in bot.texts())
    await dp.feed_update(bot, make_update_callback(make_callback(7003, user_a, "forget:yes")))
    async with ctx.db.session() as session:
        assert await UserRepository(session).get_by_telegram_id(7003) is None
    assert any("удален" in t.lower() for t in bot.texts())
