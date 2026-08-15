"""Сервис изображений: модерация -> структурированный промпт -> очередь -> ComfyUI.

Задача создаётся в БД и уходит в asyncio-очередь; воркер генерирует картинку,
сохраняет ассет и отправляет пользователю. Ошибки пользователю сообщаются
без внутренних путей и stack trace.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import timedelta

from aiogram import Bot
from aiogram.types import FSInputFile

from src.config import Settings
from src.database.base import Database
from src.database.models import User
from src.database.repositories import (
    AssetRepository,
    JobRepository,
    PreferencesRepository,
)
from src.prompts import PromptLibrary
from src.providers.base import (
    ImageProvider,
    ImageProviderError,
    ImageProviderUnavailable,
    ImageRequest,
    LLMProvider,
    LLMUnavailable,
)
from src.services.audit import AuditService
from src.services.consent import ConsentService
from src.services.moderation import ModerationService
from src.services.storage import StorageService
from src.utils import extract_json, truncate, utcnow

logger = logging.getLogger(__name__)


@dataclass
class SubmitResult:
    ok: bool
    job_id: int | None = None
    refusal_code: str | None = None
    refusal_text: str | None = None


class ImageService:
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
        self.queue: asyncio.Queue[int] = asyncio.Queue(maxsize=200)

    # ------------------------------------------------------------------ приём задачи

    async def submit(self, user: User, text: str, tg_message_id: int | None) -> SubmitResult:
        """Проверки + создание задачи. Возвращает отказ или id задачи."""
        text = text.strip()
        if not text:
            return SubmitResult(ok=False, refusal_code="empty", refusal_text="Опиши, что нарисовать.")

        # 1. Быстрая блоклист-проверка
        decision = self.moderation.check_image_blocklist(text)
        if decision.blocked:
            await self.audit.log(
                "moderation_blocked_image",
                user=user,
                meta={"reason": decision.reason_code},
            )
            return SubmitResult(
                ok=False,
                refusal_code=decision.reason_code,
                refusal_text=self.moderation.refusal_text(decision.reason_code),
            )

        # 2. LLM-судья
        judge = await self.moderation.judge_image_request(text)
        if judge.blocked:
            await self.audit.log(
                "moderation_blocked_image_llm",
                user=user,
                meta={"reason": judge.reason_code},
            )
            return SubmitResult(
                ok=False,
                refusal_code=judge.reason_code,
                refusal_text=self.moderation.refusal_text(judge.reason_code),
            )

        # 3. Структурирование запроса в ImagePrompt (с учётом наряда и стиля)
        async with self.db.session() as session:
            prefs = await PreferencesRepository(session).get_or_create(user)
            outfit = prefs.outfit
            image_style = prefs.image_style
        image_prompt = await self._build_image_prompt(text, outfit=outfit, image_style=image_style)

        # 4. Эротический запрос требует отдельного NSFW-согласия
        if image_prompt.nsfw and not await self.consent.has_nsfw_consent(user):
            await self.audit.log("image_nsfw_consent_required", user=user)
            return SubmitResult(
                ok=False,
                refusal_code="nsfw_consent_required",
                refusal_text=(
                    "Этот запрос — взрослый, а у тебя пока нет согласия на NSFW-режим. "
                    "Открой /mode и прими отдельное согласие — тогда я смогу его нарисовать."
                ),
            )

        # 5. Rate limit: не чаще одного /photo в N минут (0 = без ограничения)
        if self.settings.image_photo_rate_limit_minutes > 0:
            async with self.db.session() as session:
                last = await JobRepository(session).last_job_created_at(user.id)
                if last is not None:
                    window = timedelta(minutes=self.settings.image_photo_rate_limit_minutes)
                    if (utcnow() - last) < window:
                        return SubmitResult(
                            ok=False,
                            refusal_code="rate_limited",
                            refusal_text=(
                                "Не так быстро 🙂 Подожди немного между запросами картинок "
                                f"(лимит — одна картинка в {self.settings.image_photo_rate_limit_minutes} минут)."
                            ),
                        )

        # 6. Создаём задачу и ставим в очередь
        async with self.db.session() as session:
            job = await JobRepository(session).create_image_job(
                user,
                text,
                tg_message_id,
                image_prompt_json=json.dumps(
                    {
                        "prompt": image_prompt.prompt,
                        "negative_prompt": image_prompt.negative_prompt,
                        "width": image_prompt.width,
                        "height": image_prompt.height,
                        "steps": image_prompt.steps,
                        "cfg": image_prompt.cfg,
                        "seed": image_prompt.seed,
                        "nsfw": image_prompt.nsfw,
                    },
                    ensure_ascii=False,
                ),
            )
            job_id = job.id
        try:
            self.queue.put_nowait(job_id)
        except asyncio.QueueFull:
            async with self.db.session() as session:
                queued_job = await JobRepository(session).get(job_id)
                if queued_job is not None:
                    await JobRepository(session).set_status(queued_job, "cancelled")
            return SubmitResult(
                ok=False,
                refusal_code="queue_full",
                refusal_text="Очередь генерации переполнена, попробуй чуть позже.",
            )
        await self.audit.log("image_job_queued", user=user, meta={"job_id": job_id})
        return SubmitResult(ok=True, job_id=job_id)

    async def _build_image_prompt(
        self, text: str, *, outfit: str | None = None, image_style: str = "realistic"
    ) -> ImageRequest:
        """LLM преобразует запрос в структурированный ImagePrompt."""
        request_text = text
        if outfit:
            request_text = f"{text} (сейчас Лилит одета: {outfit})"
        if self.settings.comfyui_nsfw_extreme:
            request_text = (
                f"{request_text} (ЭКСТРЕМАЛЬНЫЙ NSFW: если запрос эротический — "
                "добавь теги hardcore, detailed genitals, explicit sex)"
            )
        style_hint = (
            "photorealistic, realistic photo, 8k"
            if image_style == "realistic"
            else "anime style, anime art, 2d illustration, cel shading, vibrant"
        )
        prompt = self.prompts.image_prompt_prompt.format(
            request=truncate(request_text, 1500),
            character_sheet=self.prompts.character_sheet,
            default_width=self.settings.default_image_size[0],
            default_height=self.settings.default_image_size[1],
            default_steps=self.settings.image_steps,
            default_cfg=self.settings.image_cfg,
            style_hint=style_hint,
        )
        try:
            raw = await self.llm.chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=600)
            data = extract_json(raw)
        except (LLMUnavailable, ValueError):
            logger.warning("Не удалось структурировать промпт изображения — используются дефолты")
            data = None
        if not isinstance(data, dict):
            data = {}
        width, height = self.settings.default_image_size
        # Fallback-промпт (если LLM-модуль не вернул JSON): НЕ отправляем сырой
        # русский текст — модель-художник его не понимает и рисует «что попало».
        # Вместо этого берём английский шаблон с описанием взрослой девушки.
        # Fallback: если пользователь не просил иную внешность — рисуем ЛИТЛИТ
        # (якорь внешности), а не «asian». «Азиатка» рисуется только если
        # пользователь явно её попросил (тогда перевод даст asian).
        if "азиат" in text.lower():
            fallback_subject = "asian woman, 24 years old"
        else:
            fallback_subject = (
                "1girl, red hair in two pigtails with black ribbons, green eyes, "
                "pale skin, freckles, tall, slim, high cheekbones, 24 years old, "
                "white blouse, pleated plaid mini skirt, thigh-high stockings"
            )
        extreme_tags = (
            ", hardcore, detailed genitals, explicit sex"
            if self.settings.comfyui_nsfw_extreme
            else ""
        )
        fallback_prompt = (
            fallback_subject + ", "
            + _translate_request_to_tags(text)
            + (f", wearing {outfit}" if outfit else "")
            + ", nude, topless, explicit, nsfw, uncensored, full body, "
            "sensual pose" + extreme_tags + ", " + style_hint
        )
        return ImageRequest(
            prompt=str(data.get("prompt") or fallback_prompt),
            negative_prompt=str(data.get("negative_prompt") or self.prompts.default_negative_prompt),
            width=width,
            height=height,
            steps=int(data.get("steps", self.settings.image_steps)),
            cfg=float(data.get("cfg", self.settings.image_cfg)),
            seed=int(data.get("seed", -1)),
            nsfw=bool(data.get("nsfw", False)) or _is_adult_request(text),
        )

    # ------------------------------------------------------------------ выполнение (воркер)

    async def run_job(self, job_id: int, bot: Bot) -> None:
        """Выполняет задачу генерации и отправляет результат пользователю."""
        async with self.db.session() as session:
            job = await JobRepository(session).get(job_id)
            if job is None or job.status != "queued":
                return
            await JobRepository(session).set_status(job, "running")
            request = json.loads(job.image_prompt_json or "{}")
            telegram_user_id = job.telegram_user_id
            user_id = job.user_id

        image_request = ImageRequest(
            prompt=str(request.get("prompt", job.request_text)),
            negative_prompt=str(request.get("negative_prompt", "")),
            width=int(request.get("width", 512)),
            height=int(request.get("height", 768)),
            steps=int(request.get("steps", self.settings.image_steps)),
            cfg=float(request.get("cfg", self.settings.image_cfg)),
            seed=int(request.get("seed", -1)),
            nsfw=bool(request.get("nsfw", False)),
        )

        temp_path = self.storage.new_temp_path("img", ".png")
        try:
            try:
                images = await self.provider.generate(image_request)
            except ImageProviderUnavailable:
                await self._fail(job_id, "image_provider_unavailable")
                await self._notify(
                    bot,
                    telegram_user_id,
                    "Не получилось создать изображение: генератор картинок сейчас недоступен. Попробуй чуть позже.",
                )
                return
            except ImageProviderError:
                await self._fail(job_id, "generation_failed")
                await self._notify(
                    bot,
                    telegram_user_id,
                    "Не получилось создать изображение — что-то пошло не так при "
                    "генерации. Попробуй другой запрос или позже.",
                )
                return
            if not images:
                raise ImageProviderError("no images")

            temp_path.write_bytes(images[0])
            async with self.db.session() as session:
                await AssetRepository(session).add(
                    _user_proxy(user_id, telegram_user_id),
                    asset_type="image",
                    file_path=str(temp_path),
                    mime_type="image/png",
                    size_bytes=temp_path.stat().st_size,
                    job_id=job_id,
                    expires_at=utcnow() + timedelta(hours=self.settings.media_ttl_hours),
                )

            await bot.send_photo(
                chat_id=telegram_user_id,
                photo=FSInputFile(str(temp_path)),
                caption="🎨 Готово!",
            )
            await self._done(job_id)
            await self.audit.log("image_job_done", telegram_user_id=telegram_user_id, meta={"job_id": job_id})
        except ImageProviderError as exc:
            await self._fail(job_id, "generation_failed")
            await self._notify(bot, telegram_user_id, "Не получилось создать изображение, попробуй позже.")
            logger.warning("Ошибка генерации (job %s): %s", job_id, exc)
        except Exception:  # noqa: BLE001 — пользователю уходит только общий текст
            await self._fail(job_id, "internal_error")
            await self._notify(
                bot,
                telegram_user_id,
                "Что-то пошло не так при создании изображения. Попробуй ещё раз чуть позже.",
            )
            logger.exception("Непредвиденная ошибка генерации (job %s)", job_id)
        finally:
            self.storage.remove(temp_path)

    async def _fail(self, job_id: int, error_code: str) -> None:
        async with self.db.session() as session:
            job = await JobRepository(session).get(job_id)
            if job is not None:
                await JobRepository(session).set_status(job, "failed", error_code=error_code)
        await self.audit.log(
            "image_job_failed",
            meta={"job_id": job_id, "error_code": error_code},
        )

    async def _done(self, job_id: int) -> None:
        async with self.db.session() as session:
            job = await JobRepository(session).get(job_id)
            if job is not None:
                await JobRepository(session).set_status(job, "done")

    async def _notify(self, bot: Bot, chat_id: int, text: str) -> None:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось уведомить пользователя %s: %s", chat_id, exc)


def _user_proxy(user_id: int, telegram_user_id: int) -> User:
    """Лёгкая заглушка User для репозитория ассетов (нужны только id)."""
    from src.database.models import User as UserModel

    user = UserModel()
    user.id = user_id
    user.telegram_user_id = telegram_user_id
    return user


def _translate_request_to_tags(text: str) -> str:
    """Переводит ключевые слова запроса в английские теги для fallback-промпта."""
    mapping = {
        "азиат": "asian",
        "брюнет": "brunette, dark hair",
        "блондин": "blonde",
        "рыж": "redhead",
        "сексуальн": "sexy, attractive",
        "красив": "beautiful, gorgeous",
        "гол": "nude, topless",
        "обнаж": "nude, topless",
        "эрот": "erotic, explicit",
        "стройн": "slim, fit",
        "пышн": "curvy, voluptuous",
        "высок": "tall",
        "молод": "young adult",
        "девушк": "woman, girl",
        "женщин": "woman",
        "в платье": "in elegant dress",
        "в белье": "in lingerie",
        "в купальник": "in bikini",
        "вечерн": "evening",
        "закат": "sunset",
        "пляж": "on the beach",
        "спальн": "in bedroom",
        "ванн": "in bathroom",
    }
    tags = []
    low = text.lower()
    for ru, en in mapping.items():
        if ru in low:
            tags.append(en)
    return ", ".join(tags) if tags else "adult woman"


def _is_adult_request(text: str) -> bool:
    low = text.lower()
    return any(
        w in low
        for w in ("гол", "обнаж", "секс", "эрот", "ню", "nude", "naked", "nsfw")
    )
