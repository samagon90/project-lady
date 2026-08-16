"""Долговременная память: извлечение фактов, семантика, суммаризация, контекст."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from src.config import Settings
from src.database.base import Database
from src.database.models import Conversation, User
from src.database.repositories import (
    MemoryRepository,
    MessageRepository,
    PreferencesRepository,
    SummaryRepository,
)
from src.prompts import PromptLibrary
from src.providers.base import LLMProvider, LLMUnavailable
from src.providers.embeddings import EmbeddingsService
from src.utils import extract_json, truncate

logger = logging.getLogger(__name__)

MEMORY_CATEGORIES = {
    "profile": "общие сведения о пользователе",
    "preferences": "предпочтения и интересы",
    "boundaries": "границы и нежелательные темы",
    "relationship": "развитие отношений с персонажем",
    "events": "важные события из жизни пользователя",
    "conversation_style": "желаемый стиль общения",
}

CATEGORY_LABELS_RU = {
    "profile": "Профиль",
    "preferences": "Предпочтения",
    "boundaries": "Границы",
    "relationship": "Отношения",
    "events": "События",
    "conversation_style": "Стиль общения",
}


@dataclass
class MemoryContext:
    """Компактный контекст для LLM: память + настройки пользователя."""

    block_text: str = ""
    summaries: list[str] = field(default_factory=list)
    mode: int = 0
    voice_enabled: bool = False
    name: str | None = None
    speech_style: str | None = None


class MemoryService:
    def __init__(
        self,
        db: Database,
        llm: LLMProvider,
        embeddings: EmbeddingsService,
        settings: Settings,
        prompts: PromptLibrary,
    ) -> None:
        self.db = db
        self.llm = llm
        self.embeddings = embeddings
        self.settings = settings
        self.prompts = prompts
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ контекст

    async def build_context(self, user: User, query_text: str) -> MemoryContext:
        """Собирает компактный контекст ТОЛЬКО для этого пользователя."""
        async with self.db.session() as session:
            prefs = await PreferencesRepository(session).get_or_create(user)
            memories = await MemoryRepository(session).list_for_user(user.id)
            summaries_repo = SummaryRepository(session)
            summaries = await summaries_repo.recent(user.id, limit=2)

        relevant = await self._semantic_search(user, query_text, memories)
        block_parts: list[str] = []

        if prefs.name:
            block_parts.append(f"Имя/обращение: {prefs.name} (обращение на «{prefs.address_term}»)")
        if prefs.pronouns:
            block_parts.append(f"Местоимения: {prefs.pronouns}")
        if prefs.interests:
            block_parts.append(f"Интересы: {truncate(prefs.interests, 300)}")
        if prefs.boundaries:
            block_parts.append(f"Границы пользователя: {truncate(prefs.boundaries, 300)}")

        # День рождения: если СЕГОДНЯ — Лилит обязательно поздравляет (v2.1)
        if prefs.birthday:
            from src.utils import utcnow

            today_md = utcnow().strftime("%m-%d")
            if prefs.birthday == today_md:
                block_parts.append(
                    "🎂 СЕГОДНЯ ДЕНЬ РОЖДЕНИЯ ПОЛЬЗОВАТЕЛЯ! Обязательно поздравить "
                    "его/её тепло, нежно и игриво, устроить маленький праздник словами."
                )
            else:
                block_parts.append(
                    f"День рождения пользователя: {prefs.birthday} (не сегодня, но помни)"
                )

        if relevant:
            lines = [
                f"- [{item.category}] {item.fact}"
                for item in relevant
                if item.sensitivity in self.settings.memory_store_sensitivity.split(",")
            ]
            if lines:
                block_parts.append("Факты о пользователе:\n" + "\n".join(lines[: self.settings.memory_top_k]))

        if summaries:
            block_parts.append(
                "Краткое содержание более ранних диалогов:\n"
                + "\n".join(f"- {truncate(s.summary, 400)}" for s in summaries)
            )

        # Лорбук (книга мира Лилит): подмешиваем записи, чьи триггеры
        # упомянул пользователь — как в SillyTavern/HammerAI. Это делает
        # «мир» Лилит стабильным: дом, кот, музыка — всегда одни и те же.
        from src.prompts import lorebook_for_query

        lore = lorebook_for_query(self.prompts.lorebook_entries, query_text)
        if lore:
            block_parts.append(
                "Твоя жизнь (вспомни и обыграй, если уместно):\n"
                + "\n".join(f"- {entry['text']}" for entry in lore[:3])
            )

        return MemoryContext(
            block_text="\n".join(block_parts),
            summaries=[s.summary for s in summaries],
            mode=prefs.mode,
            voice_enabled=prefs.voice_enabled,
            name=prefs.name,
            speech_style=prefs.speech_style,
        )

    async def _semantic_search(self, user: User, query: str, memories: list) -> list:
        """Семантический поиск по памяти пользователя (изолирован по telegram_user_id)."""
        if not memories:
            return []
        query_vec = await self.embeddings.embed_one(query)
        if query_vec is None:
            return memories[: self.settings.memory_top_k]
        # ВАЖНО: фильтрация по владельцу прямо в индексе (по telegram_user_id)
        allowed = {user.telegram_user_id}
        hits = self.embeddings.store.search(query_vec, self.settings.memory_top_k * 2, allowed_owner_ids=allowed)
        if not hits:
            return []
        ids = [item_id for item_id, _score in hits]
        async with self.db.session() as session:
            return await MemoryRepository(session).by_ids(user.id, ids)

    # ------------------------------------------------------------------ извлечение фактов

    async def extract_facts(self, user: User, conversation: Conversation) -> int:
        """Отдельный этап извлечения долговременных фактов из диалога."""
        async with self._lock:
            async with self.db.session() as session:
                messages = await MessageRepository(session).recent(user.id, conversation.id, limit=12)
                existing = await MemoryRepository(session).list_for_user(user.id, limit=20)
            if not messages:
                return 0
            dialogue = "\n".join(f"{m.role}: {m.content}" for m in messages)
            prompt = self.prompts.extraction_prompt.format(
                dialogue=truncate(dialogue, 6000),
                categories=", ".join(MEMORY_CATEGORIES.keys()),
                existing_facts="\n".join(f"- {m.fact}" for m in existing) or "—",
            )
            try:
                raw = await self.llm.chat([{"role": "user", "content": prompt}], temperature=0.0, max_tokens=800)
            except LLMUnavailable:
                logger.warning("Извлечение фактов пропущено: LLM недоступен")
                return 0
            try:
                facts = extract_json(raw)
            except ValueError:
                logger.warning("Некорректный ответ LLM при извлечении фактов")
                return 0
            if not isinstance(facts, list):
                return 0

            stored = 0
            for item in facts[:10]:
                if not isinstance(item, dict):
                    continue
                fact = str(item.get("fact", "")).strip()
                if not fact or len(fact) > 400:
                    continue
                category = str(item.get("category", "profile"))
                if category not in MEMORY_CATEGORIES:
                    category = "profile"
                confidence = float(item.get("confidence", 0.8))
                sensitivity = str(item.get("sensitivity", "low"))
                if sensitivity not in ("low", "medium", "high"):
                    sensitivity = "low"
                if confidence < self.settings.memory_min_confidence:
                    continue
                if sensitivity not in self.settings.memory_store_sensitivity.split(","):
                    continue
                expires = _parse_expires(item.get("expires_at"))
                if await self._is_duplicate(user, fact):
                    continue
                await self._store_fact(
                    user,
                    category=category,
                    fact=fact,
                    confidence=confidence,
                    sensitivity=sensitivity,
                    source_message_id=messages[-1].id,
                    expires_at=expires,
                )
                stored += 1
            if stored:
                logger.info("Память пользователя %s: сохранено фактов %s", user.telegram_user_id, stored)
            return stored

    async def _is_duplicate(self, user: User, fact: str) -> bool:
        vec = await self.embeddings.embed_one(fact)
        if vec is None:
            return False
        hits = self.embeddings.store.search(vec, 1, allowed_owner_ids={user.id})
        if not hits:
            return False
        item_id, score = hits[0]
        return score > 0.93

    async def _store_fact(
        self,
        user: User,
        *,
        category: str,
        fact: str,
        confidence: float,
        sensitivity: str,
        source_message_id: int | None,
        expires_at,
    ) -> None:
        vec = await self.embeddings.embed_one(fact)
        blob = self.embeddings.pack(vec) if vec else None
        async with self.db.session() as session:
            repo = MemoryRepository(session)
            item = await repo.add(
                user,
                category=category,
                fact=fact,
                confidence=confidence,
                sensitivity=sensitivity,
                source_message_id=source_message_id,
                embedding=blob,
                expires_at=expires_at,
            )
        if vec is not None:
            self.embeddings.store.add(item.id, user.telegram_user_id, vec)

    # ------------------------------------------------------------------ суммаризация

    async def maybe_summarize(self, user: User, conversation: Conversation) -> None:
        """Суммаризирует старые сообщения диалога, чтобы контекст не раздувался."""
        async with self.db.session() as session:
            messages_repo = MessageRepository(session)
            total = await messages_repo.count_in_conversation(conversation.id)
            if total < self.settings.memory_summarize_every_n_messages:
                return
            old = await messages_repo.oldest_for_summary(
                conversation.id,
                limit=self.settings.memory_summarize_max_history // 2,
            )
            if not old:
                return
            dialogue = "\n".join(f"{m.role}: {truncate(m.content, 500)}" for m in old)
            prompt = self.prompts.summarization_prompt.format(dialogue=truncate(dialogue, 8000))
        try:
            raw = await self.llm.chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=400)
        except LLMUnavailable:
            logger.warning("Суммаризация пропущена: LLM недоступен")
            return
        summary = raw.strip().strip('"')
        if not summary:
            return
        async with self.db.session() as session:
            summaries = SummaryRepository(session)
            await summaries.add(user, conversation, truncate(summary, 2000), old[0].id, old[-1].id)
            # Старые сообщения больше не нужны для контекста
            await MessageRepository(session).delete_old_messages(user.id, old[-1].id)
        logger.info("Диалог пользователя %s суммаризирован", user.telegram_user_id)

    # ------------------------------------------------------------------ просмотр/удаление

    async def overview(self, user: User) -> dict[str, Any]:
        async with self.db.session() as session:
            repo = MemoryRepository(session)
            counts = await repo.counts_by_category(user.id)
            recent = await repo.list_for_user(user.id, limit=10)
        return {
            "counts": counts,
            "recent": [
                {
                    "category": item.category,
                    "fact": item.fact,
                    "created_at": item.created_at,
                    "confidence": item.confidence,
                }
                for item in recent
            ],
        }

    async def remove_all_for_user(self, user: User) -> None:
        """Удаляет память пользователя из БД и из векторного индекса."""
        async with self.db.session() as session:
            repo = MemoryRepository(session)
            items = await repo.list_for_user(user.id)
            for item in items:
                self.embeddings.store.remove(item.id)
            for item in items:
                await session.delete(item)
        logger.info("Память пользователя %s удалена", user.telegram_user_id)


def _parse_expires(value: Any):
    from datetime import datetime as dt

    if isinstance(value, str):
        try:
            return dt.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None
    return None
