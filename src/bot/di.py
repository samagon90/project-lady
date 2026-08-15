"""DI-контейнер: сборка AppContext из настроек и провайдеров."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import cast

from src.config import Settings
from src.database.base import Database
from src.prompts import PromptLibrary
from src.providers.base import (
    EmbeddingsProvider,
    ImageProvider,
    LLMProvider,
    TTSProvider,
)
from src.providers.comfyui import ComfyUIProvider
from src.providers.embeddings import EmbeddingsService, SemanticMemoryStore
from src.providers.ollama import OllamaLLMProvider
from src.providers.piper import PiperTTSProvider
from src.services.audit import AuditService
from src.services.chat import ChatService
from src.services.consent import ConsentService
from src.services.image import ImageService
from src.services.memory import MemoryService
from src.services.moderation import ModerationService
from src.services.storage import StorageService
from src.services.tts import TTSService

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Контейнер зависимостей. Все сервисы — синглтоны на время жизни процесса."""

    settings: Settings
    db: Database
    llm: LLMProvider
    embeddings: EmbeddingsService
    image_provider: ImageProvider
    tts_provider: TTSProvider
    prompts: PromptLibrary
    storage: StorageService
    audit: AuditService
    moderation: ModerationService
    consent: ConsentService
    memory: MemoryService
    chat: ChatService
    image_service: ImageService
    tts: TTSService
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    background_tasks: list[asyncio.Task] = field(default_factory=list)

    async def warmup(self) -> None:
        """Прогрев семантического индекса и проверка доступности моделей."""
        async with self.db.session() as session:
            rows = await _all_embeddings(session)
        self.embeddings.load_all(rows)
        await self._check_models()

    async def _check_models(self) -> None:
        checks = [
            ("LLM (Ollama)", self.llm.health()),
            ("Изображения (ComfyUI)", self.image_provider.health()),
            ("TTS (Piper)", self.tts_provider.health()),
        ]
        for name, coro in checks:
            try:
                ok = await coro
            except Exception:
                ok = False
            if ok:
                logger.info("Доступен: %s", name)
            else:
                logger.warning(
                    "НЕ доступен: %s — бот продолжит работу, но функция будет недоступна до запуска сервиса",
                    name,
                )

    async def delete_user_data(self, user) -> None:
        """Полное каскадное удаление данных пользователя (/forget_me)."""
        from sqlalchemy import delete

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

        # Файлы пользователя
        async with self.db.session() as session:
            files = await _asset_files(session, user.id)
        for file_path in files:
            self.storage.unlink_if_exists(file_path)
        # Векторы из индекса
        await self.memory.remove_all_for_user(user)
        # Каскадное удаление всех записей (порядок — от детей к родителям)
        tables = [
            AuditEvent,
            GeneratedAsset,
            GenerationJob,
            ConversationSummary,
            Message,
            Conversation,
            MemoryItem,
            UserConsent,
            UserPreferences,
        ]
        # Фиксируем факт удаления ДО очистки: запись аудита удалится вместе с остальными
        await self.audit.log("user_deleted", telegram_user_id=user.telegram_user_id)
        async with self.db.session() as session:
            for table in tables:
                column_name = "telegram_user_id"
                column = getattr(table, column_name)
                await session.execute(
                    delete(table).where(column == user.telegram_user_id)  # type: ignore[attr-defined]
                )
            await session.execute(delete(User).where(User.id == user.id))

    async def shutdown(self) -> None:
        self.stop_event.set()
        for task in list(self.background_tasks):
            if not task.done():
                task.cancel()
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
        self.background_tasks.clear()
        if isinstance(self.llm, OllamaLLMProvider):
            await self.llm.close()
        if isinstance(self.image_provider, ComfyUIProvider):
            await self.image_provider.close()
        await self.db.close()


async def _all_embeddings(session):
    from src.database.repositories import MemoryRepository

    return await MemoryRepository(session).all_embeddings()


async def _asset_files(session, user_id: int) -> list[str]:
    from src.database.repositories import AssetRepository

    return await AssetRepository(session).files_for_user(user_id)


def build_app_context(
    settings: Settings,
    *,
    llm: LLMProvider | None = None,
    embeddings_provider: EmbeddingsProvider | None = None,
    image_provider: ImageProvider | None = None,
    tts_provider: TTSProvider | None = None,
    db: Database | None = None,
) -> AppContext:
    """Создаёт контейнер. В тестах провайдеры можно подменить."""
    database = db or Database(settings.database_url)
    prompts = PromptLibrary()

    llm_provider = llm or OllamaLLMProvider(
        settings.llm_base_url,
        settings.llm_model,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
        retries=settings.llm_retries,
    )

    # Ollama умеет и chat, и embeddings — поэтому LLM-провайдер используется
    # как embeddings-провайдер, если не передан отдельный.
    embed_provider: EmbeddingsProvider = (
        embeddings_provider if embeddings_provider is not None else cast(EmbeddingsProvider, llm_provider)
    )
    embeddings = EmbeddingsService(
        embed_provider,
        SemanticMemoryStore(settings.embedding_dim),
        model=settings.embedding_model,
    )

    ref_image = None
    if settings.comfyui_reference_image is not None:
        ref_path = settings.resolve_path(settings.comfyui_reference_image)
        if ref_path.exists():
            ref_image = ref_path
    image = image_provider or ComfyUIProvider(
        settings.comfyui_base_url,
        settings.resolved_workflow_path,
        checkpoint=settings.comfyui_checkpoint,
        lora=settings.comfyui_lora,
        nsfw_checkpoint=settings.comfyui_nsfw_checkpoint,
        nsfw_lora=settings.comfyui_nsfw_lora,
        reference_image=ref_image,
        timeout_seconds=settings.comfyui_timeout_seconds,
        poll_interval_seconds=settings.comfyui_poll_interval_seconds,
    )

    tts = tts_provider or PiperTTSProvider(
        settings.piper_binary,
        settings.resolved_piper_voice_model,
        settings.resolved_piper_voice_config or settings.piper_auto_config,
        length_scale=settings.piper_length_scale,
    )

    storage = StorageService(settings)
    audit = AuditService(database, enabled=settings.audit_enabled)
    moderation = ModerationService(database, llm_provider, prompts)
    consent = ConsentService(database, audit)
    memory = MemoryService(database, llm_provider, embeddings, settings, prompts)
    chat = ChatService(
        database, llm_provider, memory, moderation, consent, audit, settings, prompts
    )
    image_service = ImageService(database, llm_provider, image, moderation, consent, storage, audit, settings, prompts)
    tts_service = TTSService(tts, settings, storage)

    return AppContext(
        settings=settings,
        db=database,
        llm=llm_provider,
        embeddings=embeddings,
        image_provider=image,
        tts_provider=tts,
        prompts=prompts,
        storage=storage,
        audit=audit,
        moderation=moderation,
        consent=consent,
        memory=memory,
        chat=chat,
        image_service=image_service,
        tts=tts_service,
    )
