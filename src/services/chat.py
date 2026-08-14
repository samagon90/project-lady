"""Чат-сервис: сборка контекста, вызов LLM, сохранение диалога.

Вся логика построена вокруг одного пользователя: профиль, последние
сообщения и воспоминания загружаются строго по telegram_user_id.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from src.config import Settings
from src.database.base import Database
from src.database.models import User
from src.database.repositories import (
    ConversationRepository,
    MessageRepository,
    UserRepository,
)
from src.prompts import PromptLibrary
from src.providers.base import LLMProvider, LLMUnavailable
from src.services.audit import AuditService
from src.services.memory import MemoryService
from src.services.moderation import ModerationService
from src.utils import truncate

logger = logging.getLogger(__name__)


@dataclass
class ChatResult:
    text: str
    voice_text: str | None = None
    blocked: bool = False


class ChatService:
    def __init__(
        self,
        db: Database,
        llm: LLMProvider,
        memory: MemoryService,
        moderation: ModerationService,
        audit: AuditService,
        settings: Settings,
        prompts: PromptLibrary,
    ) -> None:
        self.db = db
        self.llm = llm
        self.memory = memory
        self.moderation = moderation
        self.audit = audit
        self.settings = settings
        self.prompts = prompts
        self.background_tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ основной вызов

    async def handle_message(self, user: User, text: str, tg_message_id: int | None) -> ChatResult:
        text = text.strip()
        if not text:
            return ChatResult(text="", blocked=False)

        # Модерация входящего текста (быстрый блоклист)
        decision = self.moderation.check_text_blocklist(text)
        if decision.blocked:
            await self.audit.log(
                "moderation_blocked_chat",
                user=user,
                meta={"reason": decision.reason_code},
            )
            return ChatResult(text=self.moderation.refusal_text(decision.reason_code), blocked=True)

        async with self.db.session() as session:
            users = UserRepository(session)
            await users.touch(user)
            conversations = ConversationRepository(session)
            conversation = await conversations.get_active(user)
            messages = MessageRepository(session)
            await messages.add(conversation, "user", text, tg_message_id)

        ctx = await self.memory.build_context(user, text)
        system = self.prompts.system_prompt(user, ctx)
        messages_for_llm: list[dict[str, str]] = [{"role": "system", "content": system}]
        if ctx.block_text:
            messages_for_llm.append(
                {
                    "role": "system",
                    "content": "Память и контекст о пользователе:\n" + ctx.block_text,
                }
            )
        async with self.db.session() as session:
            recent = await MessageRepository(session).recent(
                user.id, conversation.id, limit=self.settings.recent_messages_for_context
            )
        for message in recent:
            messages_for_llm.append({"role": message.role, "content": message.content})

        try:
            reply = await self.llm.chat(
                messages_for_llm,
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
            )
        except LLMUnavailable as exc:
            logger.warning("LLM недоступен для пользователя %s", user.telegram_user_id)
            await self.audit.log("llm_unavailable", user=user)
            raise LLMUnavailable("Модель недоступна") from exc

        reply = reply.strip()
        reply = truncate(reply, self.settings.max_message_length)

        async with self.db.session() as session:
            conversations = ConversationRepository(session)
            conversation = await conversations.get_active(user)
            await MessageRepository(session).add(conversation, "assistant", reply)

        # Периодические фоновые задачи: извлечение фактов и суммаризация диалога
        async with self.db.session() as session:
            total = await MessageRepository(session).count_user_messages(user.id)

        if total % self.settings.memory_extract_every_n_messages == 0:
            self._spawn(self.memory.extract_facts(user, conversation), "извлечения фактов")
        if total % self.settings.memory_summarize_every_n_messages == 0:
            self._spawn(self.memory.maybe_summarize(user, conversation), "суммаризации")

        return ChatResult(text=reply, voice_text=reply)

    def _spawn(self, coro, label: str) -> None:
        async def _run() -> None:
            try:
                await coro
            except Exception:
                logger.exception("Ошибка %s", label)

        task = asyncio.create_task(_run())
        self.background_tasks.append(task)

    async def reset_conversation(self, user: User) -> None:
        """/reset — архивирует текущий диалог и начинает новый. Память сохраняется."""
        async with self.db.session() as session:
            await ConversationRepository(session).archive_active(user.id)
        await self.audit.log("conversation_reset", user=user)
