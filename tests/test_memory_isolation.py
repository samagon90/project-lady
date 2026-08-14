"""Главный тест изоляции памяти: факты пользователя A не утекают к B.

Проверяются все три канала:
1. SQL-запросы (memory items, messages);
2. семантический поиск (векторный индекс);
3. контекст, собираемый для LLM.
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.bot.di import AppContext
from src.database.models import MemoryItem, Message
from src.database.repositories import MemoryRepository, UserRepository
from src.services.memory import MemoryService
from tests.conftest import drain_background, onboard

FACTS = [
    {
        "category": "profile",
        "fact": "Пользователь любит клубнику со сливками",
        "confidence": 0.95,
        "sensitivity": "low",
        "expires_at": None,
    },
    {
        "category": "profile",
        "fact": "Пользователь живёт в Калуге",
        "confidence": 0.9,
        "sensitivity": "low",
        "expires_at": None,
    },
]


async def _prepare_a_with_facts(ctx: AppContext):
    user_a = await onboard(ctx, 9001, nsfw=False)
    ctx.chat.llm.extraction_facts = FACTS  # type: ignore[attr-defined]
    await ctx.chat.handle_message(user_a, "Моё любимое блюдо — клубника со сливками, а ещё я живу в Калуге.", 1001)
    await drain_background(ctx)
    async with ctx.db.session() as session:
        repo = MemoryRepository(session)
        items = await repo.list_for_user(user_a.id)
        assert len(items) >= 2, "факты A должны быть извлечены и сохранены"
    return user_a


async def test_no_cross_user_leak_via_sql(ctx: AppContext) -> None:
    await _prepare_a_with_facts(ctx)
    await onboard(ctx, 9002, nsfw=False)

    async with ctx.db.session() as session:
        # Память B пуста
        count_b = await session.execute(select(func.count(MemoryItem.id)).where(MemoryItem.telegram_user_id == 9002))
        assert int(count_b.scalar_one()) == 0
        # Сообщения B не содержат фактов A
        texts_b = (
            (await session.execute(select(Message.content).where(Message.telegram_user_id == 9002))).scalars().all()
        )
        assert not any("клубник" in t or "Калуг" in t for t in texts_b)


async def test_no_cross_user_leak_via_semantic_search(ctx: AppContext) -> None:
    await _prepare_a_with_facts(ctx)
    user_b = await onboard(ctx, 9003, nsfw=False)

    # Прямой поиск в индексе с правами B — пусто
    query_vec = await ctx.embeddings.embed_one("клубника со сливками")
    assert query_vec is not None
    hits = ctx.embeddings.store.search(query_vec, 10, allowed_owner_ids={9003})
    assert hits == []

    # Через MemoryService для B — пусто
    memory_service: MemoryService = ctx.memory
    context_b = await memory_service.build_context(user_b, "Что А любит есть?")
    assert "клубник" not in context_b.block_text
    assert "Калуг" not in context_b.block_text


async def test_no_cross_user_leak_via_llm_context(ctx: AppContext) -> None:
    await _prepare_a_with_facts(ctx)
    user_b = await onboard(ctx, 9004, nsfw=False)

    # B спрашивает про факт A; FakeLLM возвращает собранный для B контекст
    result = await ctx.chat.handle_message(user_b, "Что А любит есть? Где живёт А?", 2002)
    await drain_background(ctx)
    assert "клубник" not in result.text
    assert "Калуг" not in result.text

    # Контрольная проверка: A свои факты видит
    async with ctx.db.session() as session:
        user_a = await UserRepository(session).get_by_telegram_id(9001)
    result_a = await ctx.chat.handle_message(user_a, "Что я люблю есть?", 2003)
    await drain_background(ctx)
    assert "клубник" in result_a.text


async def test_memory_overview_scoped_to_user(ctx: AppContext) -> None:
    await _prepare_a_with_facts(ctx)
    user_b = await onboard(ctx, 9005, nsfw=False)
    overview_b = await ctx.memory.overview(user_b)
    assert overview_b["counts"] == {}

    async with ctx.db.session() as session:
        user_a = await UserRepository(session).get_by_telegram_id(9001)
    overview_a = await ctx.memory.overview(user_a)
    assert sum(overview_a["counts"].values()) >= 2
