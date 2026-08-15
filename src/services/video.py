"""Сервис генерации видео с Лилит (AnimateDiff через ComfyUI).

Аналогичен ImageService: модерация -> промпт -> очередь -> ComfyUI
(video-workflow) -> отправка MP4 в Telegram. Взрослый (18+) контент —
только с согласием, вымышленный персонаж.
"""
from __future__ import annotations

import asyncio
import json
import logging

from aiogram import Bot
from aiogram.types import FSInputFile

from src.config import Settings
from src.database.base import Database
from src.database.models import User
from src.database.repositories import JobRepository
from src.prompts import PromptLibrary
from src.providers.base import (
    ImageProvider,
    ImageProviderError,
    ImageProviderUnavailable,
    ImageRequest,
    LLMProvider,
)
from src.services.audit import AuditService
from src.services.consent import ConsentService
from src.services.moderation import ModerationService
from src.services.storage import StorageService
from src.utils import extract_json, truncate

logger = logging.getLogger(__name__)


class VideoService:
    def __init__(
        self,
        db: Database,
        llm: LLMProvider,
        provider: ImageProvider,
        moderation: ModerationService,
        consent: ConsentService,
        storage: StorageService,
        audit: AuditService,
        settings: Settings,
        prompts: PromptLibrary,
    ) -> None:
        self.db = db
        self.llm = llm
        self.provider = provider
        self.moderation = moderation
        self.consent = consent
        self.storage = storage
        self.audit = audit
        self.settings = settings
        self.prompts = prompts
        self.queue: asyncio.Queue[int] = asyncio.Queue(maxsize=100)

    async def submit(self, user: User, text: str, tg_message_id: int | None):
        """Проверки + создание video-задачи. Возвращает (ok, job_id, refusal)."""
        text = text.strip()
        if not text:
            return False, None, "Опиши, какое видео создать."

        # Модерация (как для изображений — жёсткая)
        decision = self.moderation.check_image_blocklist(text)
        if decision.blocked:
            await self.audit.log(
                "moderation_blocked_video", user=user, meta={"reason": decision.reason_code}
            )
            return False, None, self.moderation.refusal_text(decision.reason_code)
        judge = await self.moderation.judge_image_request(text)
        if judge.blocked:
            await self.audit.log(
                "moderation_blocked_video_llm", user=user, meta={"reason": judge.reason_code}
            )
            return False, None, self.moderation.refusal_text(judge.reason_code)

        # NSFW-проверка
        if self._is_nsfw(text) and not await self.consent.has_nsfw_consent(user):
            await self.audit.log("video_nsfw_consent_required", user=user)
            return (
                False,
                None,
                "Этот запрос — взрослый, а у тебя пока нет согласия на NSFW-режим. "
                "Открой /mode и прими отдельное согласие.",
            )

        # Промпт
        image_prompt = await self._build_video_prompt(text)
        async with self.db.session() as session:
            job = await JobRepository(session).create_image_job(
                user, text, tg_message_id,
                image_prompt_json=json.dumps(
                    {
                        "prompt": image_prompt.prompt,
                        "negative_prompt": image_prompt.negative_prompt,
                        "width": 512,
                        "height": 768,
                        "steps": 25,
                        "cfg": 6.5,
                        "seed": image_prompt.seed,
                        "nsfw": image_prompt.nsfw,
                    },
                    ensure_ascii=False,
                ),
            )
            job.job_type = "video"
            job_id = job.id
        try:
            self.queue.put_nowait(job_id)
        except asyncio.QueueFull:
            async with self.db.session() as session:
                queued_job = await JobRepository(session).get(job_id)
                if queued_job is not None:
                    await JobRepository(session).set_status(queued_job, "cancelled")
            return False, None, "Очередь видео переполнена, попробуй позже."
        await self.audit.log("video_job_queued", user=user, meta={"job_id": job_id})
        return True, job_id, None

    async def _build_video_prompt(self, text: str) -> ImageRequest:
        """Промпт для видео: тот же image-prompt + движение."""
        request_text = (
            f"{text} (ВИДЕО: добавь движение, динамичную позу, смену выражения "
            "лица, лёгкое покачивание волос; опиши действие во времени)"
        )
        try:
            raw = await self.llm.chat(
                [
                    {
                        "role": "user",
                        "content": self.prompts.image_prompt_prompt.format(
                            request=truncate(request_text, 1500),
                            character_sheet=self.prompts.character_sheet,
                            default_width=512,
                            default_height=768,
                            default_steps=25,
                            default_cfg=6.5,
                            style_hint="motion, moving, animated, video, "
                            + ("photorealistic" if "anime" not in text else "anime"),
                        ),
                    }
                ],
                temperature=0.3,
                max_tokens=600,
            )
            data = extract_json(raw)
        except Exception:  # noqa: BLE001
            data = None
        if not isinstance(data, dict):
            data = {}
        nsfw = bool(data.get("nsfw", False)) or self._is_nsfw(text)
        return ImageRequest(
            prompt=str(data.get("prompt") or f"{text}, moving, animated"),
            negative_prompt=str(
                data.get("negative_prompt") or self.prompts.default_negative_prompt
            ),
            width=512,
            height=768,
            steps=25,
            cfg=6.5,
            nsfw=nsfw,
        )

    @staticmethod
    def _is_nsfw(text: str) -> bool:
        low = text.lower()
        return any(
            w in low
            for w in ("гол", "обнаж", "секс", "эрот", "ню", "nude", "naked", "nsfw", "бель", "разде")
        )

    async def run_job(self, job_id: int, bot: Bot) -> None:
        """Выполняет видео-задачу и отправляет результат."""
        async with self.db.session() as session:
            job_row = await JobRepository(session).get(job_id)
            if job_row is None or job_row.status != "queued" or job_row.job_type != "video":
                return
            await JobRepository(session).set_status(job_row, "running")
            request = json.loads(job_row.image_prompt_json or "{}")
            telegram_user_id = job_row.telegram_user_id
        video_request = ImageRequest(
            prompt=str(request.get("prompt", "")),
            negative_prompt=str(request.get("negative_prompt", "")),
            width=512,
            height=768,
            steps=25,
            cfg=6.5,
            seed=int(request.get("seed", -1)),
            nsfw=bool(request.get("nsfw", False)),
        )
        temp_path = self.storage.new_temp_path("video", ".mp4")
        try:
            try:
                videos = await self.provider.generate(video_request)
            except ImageProviderUnavailable:
                await self._fail(job_id, "video_provider_unavailable")
                await self._notify(
                    bot, telegram_user_id,
                    "Не получилось создать видео: генератор сейчас недоступен. Попробуй позже.",
                )
                return
            except ImageProviderError:
                await self._fail(job_id, "video_generation_failed")
                await self._notify(
                    bot, telegram_user_id,
                    "Не получилось создать видео — что-то пошло не так. Попробуй другой запрос.",
                )
                return
            if not videos:
                raise ImageProviderError("no video")
            temp_path.write_bytes(videos[0])
            await bot.send_video(
                chat_id=telegram_user_id,
                video=FSInputFile(str(temp_path)),
                caption="🎬 Готово!",
                supports_streaming=True,
            )
            await self._done(job_id)
            await self.audit.log("video_job_done", telegram_user_id=telegram_user_id, meta={"job_id": job_id})
        except Exception as exc:  # noqa: BLE001
            await self._fail(job_id, "video_internal_error")
            await self._notify(
                bot, telegram_user_id, "Не получилось создать видео, попробуй позже."
            )
            logger.exception("Ошибка видео-генерации (job %s): %s", job_id, exc)
        finally:
            self.storage.remove(temp_path)

    async def _fail(self, job_id: int, code: str) -> None:
        async with self.db.session() as session:
            job = await JobRepository(session).get(job_id)
            if job is not None:
                await JobRepository(session).set_status(job, "failed", error_code=code)
        await self.audit.log("video_job_failed", meta={"job_id": job_id, "error_code": code})

    async def _done(self, job_id: int) -> None:
        async with self.db.session() as session:
            job = await JobRepository(session).get(job_id)
            if job is not None:
                await JobRepository(session).set_status(job, "done")

    async def _notify(self, bot: Bot, chat_id: int, text: str) -> None:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:  # noqa: BLE001
            logger.warning("Не удалось уведомить %s", chat_id)
