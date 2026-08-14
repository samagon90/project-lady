"""Репозитории: доступ к данным с жёсткой фильтрацией по telegram_user_id.

Все запросы, затрагивающие пользовательские данные, всегда содержат
WHERE telegram_user_id = ... — это базовая защита от утечек между пользователями.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    AuditEvent,
    Conversation,
    ConversationSummary,
    GeneratedAsset,
    GenerationJob,
    MemoryItem,
    Message,
    User,
    UserConsent,
    UserPreferences,
)
from src.utils import utcnow


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
        return result.scalar_one_or_none()

    async def create(
        self,
        telegram_user_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
    ) -> User:
        user = User(
            telegram_user_id=telegram_user_id,
            telegram_username=username,
            telegram_first_name=first_name,
            consent_step="age_gate",
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def set_consent_step(self, user: User, step: str) -> None:
        """UPDATE-запрос: работает и для detached-объектов из другой сессии."""
        await self.session.execute(
            update(User).where(User.id == user.id).values(consent_step=step)
        )

    async def touch(self, user: User) -> None:
        await self.session.execute(
            update(User).where(User.id == user.id).values(last_active_at=utcnow())
        )


class PreferencesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user(self, user_id: int) -> UserPreferences | None:
        result = await self.session.execute(select(UserPreferences).where(UserPreferences.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create(self, user: User) -> UserPreferences:
        prefs = await self.get_by_user(user.id)
        if prefs is None:
            prefs = UserPreferences(user_id=user.id, telegram_user_id=user.telegram_user_id)
            self.session.add(prefs)
            await self.session.flush()
        return prefs

    async def update_fields(self, user: User, **fields: object) -> UserPreferences:
        prefs = await self.get_or_create(user)
        for key, value in fields.items():
            setattr(prefs, key, value)
        prefs.updated_at = utcnow()
        await self.session.flush()
        return prefs


class ConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, user_id: int, consent_type: str) -> UserConsent | None:
        result = await self.session.execute(
            select(UserConsent)
            .where(
                UserConsent.user_id == user_id,
                UserConsent.consent_type == consent_type,
                UserConsent.revoked_at.is_(None),
            )
            .order_by(UserConsent.accepted_at.desc())
        )
        return result.scalars().first()

    async def add(self, user: User, consent_type: str, version: str, policy_hash: str) -> UserConsent:
        consent = UserConsent(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            consent_type=consent_type,
            version=version,
            policy_hash=policy_hash,
        )
        self.session.add(consent)
        await self.session.flush()
        return consent

    async def revoke(self, user_id: int, consent_type: str) -> None:
        await self.session.execute(
            update(UserConsent)
            .where(
                UserConsent.user_id == user_id,
                UserConsent.consent_type == consent_type,
                UserConsent.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )

    async def list_all(self, user_id: int) -> list[UserConsent]:
        result = await self.session.execute(
            select(UserConsent).where(UserConsent.user_id == user_id).order_by(UserConsent.accepted_at.desc())
        )
        return list(result.scalars().all())


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, user: User) -> Conversation:
        result = await self.session.execute(
            select(Conversation).where(Conversation.user_id == user.id, Conversation.is_active.is_(True))
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            conv = Conversation(user_id=user.id, telegram_user_id=user.telegram_user_id)
            self.session.add(conv)
            await self.session.flush()
        return conv

    async def archive_active(self, user_id: int) -> None:
        await self.session.execute(
            update(Conversation)
            .where(Conversation.user_id == user_id, Conversation.is_active.is_(True))
            .values(is_active=False, ended_at=utcnow())
        )


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        conversation: Conversation,
        role: str,
        content: str,
        tg_message_id: int | None = None,
    ) -> Message:
        message = Message(
            user_id=conversation.user_id,
            telegram_user_id=conversation.telegram_user_id,
            conversation_id=conversation.id,
            role=role,
            content=content,
            tg_message_id=tg_message_id,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def recent(self, user_id: int, conversation_id: int, limit: int) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(
                Message.user_id == user_id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def count_user_messages(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Message.id)).where(Message.user_id == user_id, Message.role == "user")
        )
        return int(result.scalar_one())

    async def count_in_conversation(self, conversation_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
        )
        return int(result.scalar_one())

    async def oldest_for_summary(self, conversation_id: int, limit: int) -> list[Message]:
        """Старые сообщения диалога (для суммаризации), начиная с самых ранних."""
        result = await self.session.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.asc()).limit(limit)
        )
        return list(result.scalars().all())

    async def delete_old_messages(self, user_id: int, before_id: int) -> int:
        """Удаляет сообщения пользователя старше before_id (уже покрытые суммаризацией)."""
        result = await self.session.execute(
            delete(Message).where(
                Message.user_id == user_id,
                Message.id < before_id,
                Message.role.in_(("user", "assistant")),
            )
        )
        return (cast(CursorResult, result)).rowcount or 0


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        user: User,
        *,
        category: str,
        fact: str,
        confidence: float,
        sensitivity: str,
        source_message_id: int | None,
        embedding: bytes | None,
        expires_at: datetime | None,
    ) -> MemoryItem:
        item = MemoryItem(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            category=category,
            fact=fact,
            confidence=confidence,
            sensitivity=sensitivity,
            source_message_id=source_message_id,
            embedding=embedding,
            expires_at=expires_at,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_for_user(self, user_id: int, limit: int | None = None) -> list[MemoryItem]:
        query = select(MemoryItem).where(MemoryItem.user_id == user_id).order_by(MemoryItem.created_at.desc())
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def by_ids(self, user_id: int, ids: list[int]) -> list[MemoryItem]:
        if not ids:
            return []
        result = await self.session.execute(
            select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.id.in_(ids))
        )
        return list(result.scalars().all())

    async def counts_by_category(self, user_id: int) -> dict[str, int]:
        result = await self.session.execute(
            select(MemoryItem.category, func.count(MemoryItem.id))
            .where(MemoryItem.user_id == user_id)
            .group_by(MemoryItem.category)
        )
        return {category: int(count) for category, count in result.all()}

    async def all_embeddings(self) -> list[tuple[int, int, bytes]]:
        """Все (id, telegram_user_id, embedding) для прогрева векторного индекса."""
        result = await self.session.execute(
            select(MemoryItem.id, MemoryItem.telegram_user_id, MemoryItem.embedding).where(
                MemoryItem.embedding.is_not(None)
            )
        )
        return [(int(row[0]), int(row[1]), bytes(row[2])) for row in result.all()]

    async def delete_expired(self, user_id: int, now: datetime) -> int:
        result = await self.session.execute(
            delete(MemoryItem).where(
                MemoryItem.user_id == user_id,
                MemoryItem.expires_at.is_not(None),
                MemoryItem.expires_at < now,
            )
        )
        return (cast(CursorResult, result)).rowcount or 0


class SummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        user: User,
        conversation: Conversation,
        summary: str,
        message_from_id: int | None,
        message_to_id: int | None,
    ) -> ConversationSummary:
        row = ConversationSummary(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            conversation_id=conversation.id,
            summary=summary,
            message_from_id=message_from_id,
            message_to_id=message_to_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent(self, user_id: int, limit: int = 3) -> list[ConversationSummary]:
        result = await self.session.execute(
            select(ConversationSummary)
            .where(ConversationSummary.user_id == user_id)
            .order_by(ConversationSummary.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_image_job(
        self,
        user: User,
        request_text: str,
        tg_message_id: int | None,
        image_prompt_json: str | None = None,
    ) -> GenerationJob:
        job = GenerationJob(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            job_type="image",
            status="queued",
            request_text=request_text,
            tg_message_id=tg_message_id,
            image_prompt_json=image_prompt_json,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: int) -> GenerationJob | None:
        result = await self.session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        return result.scalar_one_or_none()

    async def get_for_user(self, job_id: int, user_id: int) -> GenerationJob | None:
        result = await self.session.execute(
            select(GenerationJob).where(GenerationJob.id == job_id, GenerationJob.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def set_status(
        self,
        job: GenerationJob,
        status: str,
        *,
        error_code: str | None = None,
        comfyui_prompt_id: str | None = None,
        image_prompt_json: str | None = None,
    ) -> None:
        job.status = status
        job.error_code = error_code
        if comfyui_prompt_id is not None:
            job.comfyui_prompt_id = comfyui_prompt_id
        if image_prompt_json is not None:
            job.image_prompt_json = image_prompt_json
        now = utcnow()
        if status == "running":
            job.started_at = now
        if status in ("done", "failed", "cancelled"):
            job.finished_at = now
        await self.session.flush()

    async def queued_jobs(self) -> list[GenerationJob]:
        result = await self.session.execute(
            select(GenerationJob).where(GenerationJob.status == "queued").order_by(GenerationJob.id.asc())
        )
        return list(result.scalars().all())

    async def last_job_created_at(self, user_id: int) -> datetime | None:
        result = await self.session.execute(
            select(func.max(GenerationJob.created_at)).where(
                GenerationJob.user_id == user_id, GenerationJob.job_type == "image"
            )
        )
        return result.scalar_one_or_none()


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        user: User,
        *,
        asset_type: str,
        file_path: str,
        mime_type: str | None,
        size_bytes: int,
        job_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> GeneratedAsset:
        asset = GeneratedAsset(
            user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            job_id=job_id,
            asset_type=asset_type,
            file_path=file_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            expires_at=expires_at,
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def files_for_user(self, user_id: int) -> list[str]:
        result = await self.session.execute(select(GeneratedAsset.file_path).where(GeneratedAsset.user_id == user_id))
        return [str(path) for path in result.scalars().all()]

    async def expired(self, now: datetime, limit: int = 100) -> list[GeneratedAsset]:
        result = await self.session.execute(
            select(GeneratedAsset)
            .where(GeneratedAsset.expires_at.is_not(None), GeneratedAsset.expires_at < now)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, asset: GeneratedAsset) -> None:
        await self.session.delete(asset)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        event_type: str,
        *,
        user: User | None = None,
        telegram_user_id: int | None = None,
        meta: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            user_id=user.id if user else None,
            telegram_user_id=telegram_user_id
            if telegram_user_id is not None
            else (user.telegram_user_id if user else None),
            event_type=event_type,
            meta=meta or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event
