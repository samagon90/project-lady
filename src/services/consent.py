"""Согласия: age gate, базовая политика, отдельный opt-in на NSFW.

NSFW никогда не включается автоматически: требуется отдельное согласие
с версией и датой. Режим 3 (NSFW) активируется только после него.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from src.database.base import Database
from src.database.models import User
from src.database.repositories import (
    ConsentRepository,
    PreferencesRepository,
    UserRepository,
)
from src.services.audit import AuditService
from src.utils import utcnow

CONSENT_BASE_VERSION = "2026.1"
CONSENT_NSFW_VERSION = "2026.1"

POLICY_BASE_TEXT = (
    "📜 ПОЛИТИКА ОБЩЕНИЯ (версия {version}, от {date})\n\n"
    "Лилит — вымышленный ИИ-персонаж, а не реальный человек. Она не утверждает, "
    "что обладает сознанием или физическим телом.\n\n"
    "Что доступно:\n"
    "• дружеское общение и лёгкий флирт;\n"
    "• романтический режим — тёплые и близкие диалоги;\n"
    "• запоминание ваших предпочтений и истории общения (только для вас).\n\n"
    "Что хранится: профиль, предпочтения, сообщения и воспоминания — локально, "
    "на сервере бота. Вы можете просмотреть (/profile, /memory), изменить "
    "(/settings) или безвозвратно удалить (/forget_me) свои данные в любой момент.\n\n"
    "Эротический (NSFW) режим сюда НЕ входит: он включается только отдельным "
    "согласием и никогда не активируется автоматически.\n\n"
    "Нажимая «Согласен(на)», вы подтверждаете: мне есть 18 лет, я понимаю, что "
    "общаюсь с ИИ, и принимаю условия выше."
)

POLICY_NSFW_TEXT = (
    "🔞 ОТДЕЛЬНОЕ СОГЛАСИЕ НА NSFW (версия {version}, от {date})\n\n"
    "Эротический режим — только для совершеннолетних (18+), добровольно, "
    "в личных сообщениях.\n\n"
    "В этом режиме вы и Лилит можете вести взрослый эротический диалог. "
    "Остаются запрещёнными: любые темы с несовершеннолетними, насилие и "
    "принуждение, инцест, животные, реальные люди и дипфейки, шантаж и "
    "эксплуатация, инструкции для реального вреда.\n\n"
    "Вы можете отказаться от NSFW в любой момент командой /mode.\n\n"
    "Нажимая «Принимаю», вы подтверждаете: мне есть 18 лет, я добровольно "
    "включаю эротический режим и понимаю его правила."
)


def policy_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


class ConsentService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    def base_policy_text(self) -> str:
        return POLICY_BASE_TEXT.format(version=CONSENT_BASE_VERSION, date=_policy_date())

    def nsfw_policy_text(self) -> str:
        return POLICY_NSFW_TEXT.format(version=CONSENT_NSFW_VERSION, date=_policy_date())

    # ------------------------------------------------------------------ онбординг

    async def register(self, telegram_user_id: int, username: str | None, first_name: str | None) -> User:
        """Создание пользователя после age gate (step = base_pending)."""
        async with self.db.session() as session:
            users = UserRepository(session)
            user = await users.get_by_telegram_id(telegram_user_id)
            if user is None:
                user = await users.create(telegram_user_id, username=username, first_name=first_name)
            await users.set_consent_step(user, "base_pending")
        await self.audit.log("user_registered", telegram_user_id=telegram_user_id)
        return user

    async def accept_base(self, user: User) -> None:
        """Базовая политика (флирт/романтика) принята — пользователь активен."""
        async with self.db.session() as session:
            users = UserRepository(session)
            consents = ConsentRepository(session)
            await users.set_consent_step(user, "nsfw_question")
            await consents.add(user, "base", CONSENT_BASE_VERSION, policy_hash(self.base_policy_text()))
        await self.audit.log(
            "consent_base_accepted",
            user=user,
            meta={"version": CONSENT_BASE_VERSION},
        )

    async def accept_nsfw(self, user: User) -> None:
        async with self.db.session() as session:
            consents = ConsentRepository(session)
            await consents.add(user, "nsfw", CONSENT_NSFW_VERSION, policy_hash(self.nsfw_policy_text()))
        await self.audit.log(
            "consent_nsfw_accepted",
            user=user,
            meta={"version": CONSENT_NSFW_VERSION},
        )

    async def revoke_nsfw(self, user: User) -> None:
        async with self.db.session() as session:
            consents = ConsentRepository(session)
            await consents.revoke(user.id, "nsfw")
            prefs = await PreferencesRepository(session).get_or_create(user)
            if prefs.mode == 3:
                prefs.mode = 2
        await self.audit.log("consent_nsfw_revoked", user=user)

    async def complete_onboarding(self, user: User) -> None:
        async with self.db.session() as session:
            await UserRepository(session).set_consent_step(user, "active")
            await PreferencesRepository(session).get_or_create(user)

    async def has_nsfw_consent(self, user: User) -> bool:
        async with self.db.session() as session:
            consent = await ConsentRepository(session).get_active(user.id, "nsfw")
            return consent is not None

    async def has_base_consent(self, user: User) -> bool:
        async with self.db.session() as session:
            consent = await ConsentRepository(session).get_active(user.id, "base")
            return consent is not None

    async def consent_info(self, user: User) -> dict[str, datetime | str | None]:
        async with self.db.session() as session:
            consents = ConsentRepository(session)
            base = await consents.get_active(user.id, "base")
            nsfw = await consents.get_active(user.id, "nsfw")
        return {
            "base_version": base.version if base else None,
            "base_date": base.accepted_at if base else None,
            "nsfw_version": nsfw.version if nsfw else None,
            "nsfw_date": nsfw.accepted_at if nsfw else None,
        }


def _policy_date() -> str:
    return utcnow().strftime("%d.%m.%Y")
