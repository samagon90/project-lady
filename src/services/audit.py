"""Аудит безопасности: события без содержимого переписки."""

from __future__ import annotations

import json
import logging

from src.database.base import Database
from src.database.models import User
from src.database.repositories import AuditRepository

logger = logging.getLogger(__name__)


class AuditService:
    """Журнал событий. Никогда не содержит тексты сообщений и NSFW-диалогов."""

    def __init__(self, db: Database, enabled: bool = True) -> None:
        self.db = db
        self.enabled = enabled

    async def log(
        self,
        event_type: str,
        *,
        user: User | None = None,
        telegram_user_id: int | None = None,
        meta: dict | None = None,
    ) -> None:
        if not self.enabled:
            return
        safe_meta = {k: _sanitize(v) for k, v in (meta or {}).items()}
        try:
            async with self.db.session() as session:
                await AuditRepository(session).add(
                    event_type, user=user, telegram_user_id=telegram_user_id, meta=safe_meta
                )
        except Exception:  # аудит не должен ронять основной поток
            logger.exception("Не удалось записать событие аудита %s", event_type)


def _sanitize(value: object) -> object:
    """Обезличивает значения метаданных для аудита."""
    if isinstance(value, str):
        if len(value) > 200:
            return value[:200] + "…"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    try:
        return json.dumps(value, ensure_ascii=False)[:200]
    except TypeError:
        return str(value)
