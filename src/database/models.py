"""Модели данных (SQLAlchemy 2.x async).

Каждая сущность, относящаяся к пользователю, привязана к telegram_user_id.
Никакие данные разных пользователей не смешиваются на уровне схемы.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.utils import utcnow


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Шаг онбординга: age_gate -> base_pending -> nsfw_question -> active
    consent_step: Mapped[str] = mapped_column(String(32), default="age_gate")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    preferences: Mapped[UserPreferences | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    consents: Mapped[list[UserConsent]] = relationship(back_populates="user", cascade="all, delete-orphan")
    conversations: Mapped[list[Conversation]] = relationship(back_populates="user", cascade="all, delete-orphan")
    messages: Mapped[list[Message]] = relationship(back_populates="user", cascade="all, delete-orphan")
    memories: Mapped[list[MemoryItem]] = relationship(back_populates="user", cascade="all, delete-orphan")
    summaries: Mapped[list[ConversationSummary]] = relationship(back_populates="user", cascade="all, delete-orphan")
    jobs: Mapped[list[GenerationJob]] = relationship(back_populates="user", cascade="all, delete-orphan")
    assets: Mapped[list[GeneratedAsset]] = relationship(back_populates="user", cascade="all, delete-orphan")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    # Как пользователь просил себя называть / как к нему обращаться
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address_term: Mapped[str] = mapped_column(String(16), default="ты")
    pronouns: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="ru")

    # Уровень общения: 0 дружеский, 1 лёгкий флирт, 2 романтический, 3 NSFW
    mode: Mapped[int] = mapped_column(Integer, default=0)

    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    voice_speed: Mapped[float] = mapped_column(Float, default=1.0)

    # Текущий наряд Лилит для этого пользователя (например, «чёрное платье, чулки»)
    outfit: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Стиль генерации изображений/аватара: realistic | anime
    image_style: Mapped[str] = mapped_column(String(16), default="realistic")
    # Желаемая манера речи (например, «нежно и медленно»); пусто — по умолчанию
    speech_style: Mapped[str | None] = mapped_column(String(200), nullable=True)

    interests: Mapped[str | None] = mapped_column(Text, nullable=True)
    boundaries: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="preferences")


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (Index("ix_consents_user_type", "telegram_user_id", "consent_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # "base" — флирт/романтика, "nsfw" — эротический режим
    consent_type: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(16))
    policy_hash: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="consents")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    summaries: Mapped[list[ConversationSummary]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_user_created", "telegram_user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="messages")
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class MemoryItem(Base):
    """Долговременный факт о пользователе.

    Категории: profile, preferences, boundaries, relationship, events, conversation_style.
    """

    __tablename__ = "memory_items"
    __table_args__ = (Index("ix_memory_user_category", "telegram_user_id", "category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    category: Mapped[str] = mapped_column(String(32))
    fact: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    sensitivity: Mapped[str] = mapped_column(String(8), default="low")
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Вектор embeddings (float32), None если embeddings недоступны
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="memories")


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    message_from_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_to_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="summaries")
    conversation: Mapped[Conversation] = relationship(back_populates="summaries")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        Index("ix_jobs_user_created", "telegram_user_id", "created_at"),
        Index("ix_jobs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    job_type: Mapped[str] = mapped_column(String(16), default="image")
    # queued | running | done | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="queued")
    request_text: Mapped[str] = mapped_column(Text)
    image_prompt_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Код ошибки без внутренних путей и stack trace
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comfyui_prompt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="jobs")
    assets: Mapped[list[GeneratedAsset]] = relationship(back_populates="job", cascade="all, delete-orphan")


class GeneratedAsset(Base):
    __tablename__ = "generated_assets"
    __table_args__ = (Index("ix_assets_expires", "expires_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(16))  # image | voice
    file_path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    telegram_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="assets")
    job: Mapped[GenerationJob | None] = relationship(back_populates="assets")


class AuditEvent(Base):
    """Аудит безопасности. Никогда не содержит содержимое переписки."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_user_created", "telegram_user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User | None] = relationship(back_populates="audit_events")
