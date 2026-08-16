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
    PreferencesRepository,
    UserRepository,
)
from src.prompts import PromptLibrary
from src.providers.base import LLMProvider, LLMUnavailable
from src.services.audit import AuditService
from src.services.consent import ConsentService
from src.services.memory import MemoryService
from src.services.moderation import ModerationService, is_adult_request
from src.utils import contains_cjk, truncate

logger = logging.getLogger(__name__)


# Уровни отношений (геймификация, как в Replika): XP накапливается за
# сообщения, уровень растёт. Названия отражают развитие близости.
RELATIONSHIP_LEVELS: list[tuple[int, str]] = [
    (0, "Знакомство"),
    (50, "Дружба"),
    (150, "Лёгкий флирт"),
    (300, "Романтика"),
    (500, "Страсть"),
    (800, "Любовь"),
    (1200, "Родные души"),
]


def level_for_xp(xp: int) -> int:
    """Уровень (1..7) по количеству XP. Первый порог (0 XP) — это уровень 1."""
    level = 1
    for threshold, _name in RELATIONSHIP_LEVELS[1:]:
        if xp >= threshold:
            level += 1
    return min(level, len(RELATIONSHIP_LEVELS))


def level_name(level: int) -> str:
    idx = min(max(level, 1), len(RELATIONSHIP_LEVELS)) - 1
    return RELATIONSHIP_LEVELS[idx][1]


def level_progress(xp: int) -> tuple[int, int, float]:
    """Текущий уровень, XP до следующего и прогресс 0..1."""
    level = level_for_xp(xp)
    if level >= len(RELATIONSHIP_LEVELS):
        return level, 0, 1.0
    low = RELATIONSHIP_LEVELS[level - 1][0]
    high = RELATIONSHIP_LEVELS[level][0]
    return level, high - xp, (xp - low) / max(1, high - low)


@dataclass
class ChatResult:
    text: str
    voice_text: str | None = None
    blocked: bool = False
    level_up: str | None = None
    xp: int = 0
    level: int = 1


class ChatService:
    def __init__(
        self,
        db: Database,
        llm: LLMProvider,
        memory: MemoryService,
        moderation: ModerationService,
        consent: ConsentService,
        audit: AuditService,
        settings: Settings,
        prompts: PromptLibrary,
    ) -> None:
        self.db = db
        self.llm = llm
        self.memory = memory
        self.moderation = moderation
        self.consent = consent
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
        # Авто-NSFW: если у пользователя есть согласие и запрос явно взрослый —
        # отвечаем в NSFW-стиле для этого ответа (режим в настройках не меняется).
        # Это снимает лишний барьер для согласившихся пользователей.
        if ctx.mode != 3 and is_adult_request(text) and await self.consent.has_nsfw_consent(user):
            ctx.mode = 3
        # Персональная «живость» ответа (фича open-character-ai):
        # креативность и длина настраиваются в Mini App / /settings.
        async with self.db.session() as session:
            prefs = await PreferencesRepository(session).get_or_create(user)
            creativity = min(max(prefs.creativity, 0), 2)
            response_length = min(max(prefs.response_length, 0), 2)
            xp_before = prefs.xp or 0
        temperature = {0: 0.7, 1: self.settings.llm_temperature, 2: 1.35}[creativity]
        max_tokens = {0: min(300, self.settings.llm_max_tokens),
                      1: self.settings.llm_max_tokens,
                      2: 1500}[response_length]
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
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except LLMUnavailable as exc:
            logger.warning("LLM недоступен для пользователя %s", user.telegram_user_id)
            await self.audit.log("llm_unavailable", user=user)
            raise LLMUnavailable("Модель недоступна") from exc

        reply = reply.strip()
        # Авто-фикс пола: если Лилит написала о себе в мужском роде —
        # переспрашиваем модель, требуя женские окончания.
        if _has_masculine_self(reply):
            logger.warning(
                "Модель написала о себе в мужском роде (user %s) — переспрашиваю",
                user.telegram_user_id,
            )
            fix_messages = [
                *messages_for_llm,
                {"role": "assistant", "content": truncate(reply, 500)},
                {
                    "role": "user",
                    "content": (
                        "Перепиши свой ответ: ты — женщина, говори о себе ТОЛЬКО "
                        "в женском роде («я сказала», «я пришла», «я хотела», «готова»). "
                        "Исправь все мужские окончания. Только исправленный текст."
                    ),
                },
            ]
            try:
                fixed = (
                    await self.llm.chat(
                        fix_messages,
                        temperature=self.settings.llm_temperature,
                        max_tokens=self.settings.llm_max_tokens,
                    )
                ).strip()
            except LLMUnavailable:
                fixed = ""
            if fixed and not _has_masculine_self(fixed):
                reply = fixed
        # Защита от глючных моделей: если ответ содержит иероглифы (модель
        # «слетела» на китайский), переспрашиваем один раз, явно требуя русский.
        if contains_cjk(reply):
            logger.warning(
                "Модель ответила иероглифами (user %s) — переспрашиваю по-русски",
                user.telegram_user_id,
            )
            fix_messages = [
                *messages_for_llm,
                {"role": "assistant", "content": truncate(reply, 500)},
                {
                    "role": "user",
                    "content": (
                        "Пожалуйста, ответь ещё раз на мой вопрос. Отвечай СТРОГО "
                        "на русском языке, без иероглифов и без других языков."
                    ),
                },
            ]
            try:
                fixed = (
                    await self.llm.chat(
                        fix_messages,
                        temperature=self.settings.llm_temperature,
                        max_tokens=self.settings.llm_max_tokens,
                    )
                ).strip()
            except LLMUnavailable:
                fixed = ""
            if contains_cjk(fixed):
                reply = (
                    "😔 Похоже, языковая модель сбоит и отвечает не по-русски. "
                    "Это значит, что в файле .env указана глючная модель. "
                    "Откройте .env, поменяйте LLM_MODEL на dolphin-llama3:8b "
                    "(или qwen2.5:7b) и перезапустите бота."
                )
            else:
                reply = fixed
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

        # Геймификация (фича Replika): XP за сообщение, повышение уровня
        level_up_text = await self._award_xp(user, xp_before, reply)
        level = level_for_xp(xp_before)
        return ChatResult(text=reply, voice_text=reply, level_up=level_up_text, xp=xp_before, level=level)

    async def _award_xp(self, user: User, xp_before: int, reply: str) -> str | None:
        """Начисляет XP за сообщение. Возвращает текст о повышении уровня (или None).

        XP: 3 за сообщение + 2 за развёрнутый ответ. Уровень считается по
        порогам RELATIONSHIP_LEVELS (фича Replika).
        """
        gain = 3 + (2 if len(reply) > 300 else 0)
        async with self.db.session() as session:
            prefs = await PreferencesRepository(session).get_or_create(user)
            prefs.xp = (prefs.xp or 0) + gain
            await session.flush()
            xp_now = prefs.xp or 0
        old_level = level_for_xp(xp_before)
        new_level = level_for_xp(xp_now)
        if new_level > old_level:
            await self.audit.log(
                "level_up", user=user, meta={"level": new_level, "name": level_name(new_level)}
            )
            return (
                f"💖 Уровень отношений повышен: **{level_name(new_level)}**! "
                f"(уровень {new_level}/7)"
            )
        return None

    async def alternatives(self, user: User, text: str, n: int = 3) -> list[str]:
        """Свайпы (фича Character.AI / SillyTavern): несколько вариантов ответа
        на последнее сообщение пользователя. В историю НЕ сохраняются."""
        text = text.strip()
        if not text or n < 1:
            return []
        async with self.db.session() as session:
            await UserRepository(session).touch(user)
            conversation = await ConversationRepository(session).get_active(user)
        ctx = await self.memory.build_context(user, text)
        if ctx.mode != 3 and is_adult_request(text) and await self.consent.has_nsfw_consent(user):
            ctx.mode = 3
        system = self.prompts.system_prompt(user, ctx)
        messages_for_llm: list[dict[str, str]] = [{"role": "system", "content": system}]
        if ctx.block_text:
            messages_for_llm.append(
                {"role": "system", "content": "Память и контекст о пользователе:\n" + ctx.block_text}
            )
        async with self.db.session() as session:
            recent = await MessageRepository(session).recent(
                user.id, conversation.id, limit=self.settings.recent_messages_for_context
            )
        for message in recent:
            messages_for_llm.append({"role": message.role, "content": message.content})
        results: list[str] = []
        temps = (1.0, 1.3, 1.6)
        for i in range(n):
            try:
                raw = await self.llm.chat(
                    messages_for_llm,
                    temperature=temps[i % len(temps)],
                    max_tokens=self.settings.llm_max_tokens,
                )
            except LLMUnavailable:
                continue
            candidate = truncate(raw.strip(), self.settings.max_message_length)
            if candidate and candidate != text and candidate not in results:
                results.append(candidate)
        return results

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


_MASCULINE_SELF = (
    r"\b(я|а я|но я)\s+(пришёл|пришел|сказал|хотел|был|сделал|понял|устал|"
    r"готов|рад|зол|уверен|занят|согласен|любил|ждал|видел|слышал|подумал|"
    r"решил|вспомнил|забыл|нашёл|начал|закончил|ответил|спросил|посмотрел|"
    r"услышал|почувствовал|захотел|смог|сумел|привык|успел|опоздал|вернулся|"
    r"приехал|уехал|ушёл|вошёл|вышел)\b"
)


def _has_masculine_self(text: str) -> bool:
    """Есть ли в тексте мужские формы от первого лица («я пришёл», «я был»)."""
    import re

    return bool(re.search(_MASCULINE_SELF, text.lower(), re.IGNORECASE))
