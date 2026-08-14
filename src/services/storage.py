"""Работа с временными файлами: безопасные имена, каталоги, очистка."""

from __future__ import annotations

import logging
import shutil
from datetime import timedelta
from pathlib import Path

from src.config import Settings
from src.utils import ensure_dir, safe_filename

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.temp_dir = settings.resolved_temp_dir
        self.data_dir = settings.resolved_data_dir
        ensure_dir(self.temp_dir)

    def new_temp_path(self, prefix: str, suffix: str) -> Path:
        return self.temp_dir / safe_filename(prefix, suffix)

    def remove(self, path: Path) -> None:
        """Безопасное удаление файла; ошибки только логируются."""
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            logger.warning("Не удалось удалить временный файл %s: %s", path.name, exc)

    def remove_many(self, paths: list[Path]) -> None:
        for path in paths:
            self.remove(path)

    def cleanup_expired(self, ttl: timedelta) -> int:
        """Удаляет временные файлы старше ttl. Возвращает число удалённых."""
        removed = 0
        now = _now_ts()
        for path in self.temp_dir.iterdir():
            try:
                if path.is_file() and now - path.stat().st_mtime > ttl.total_seconds():
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        if removed:
            logger.info("Очистка временных файлов: удалено %s", removed)
        return removed

    def delete_tree(self, path: Path) -> None:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
        except OSError:
            pass

    def unlink_if_exists(self, path_str: str) -> None:
        """Удаление по строке пути из БД (только если путь внутри data_dir)."""
        path = Path(path_str)
        try:
            resolved = path.resolve()
        except OSError:
            return
        data_resolved = self.data_dir.resolve()
        if not str(resolved).startswith(str(data_resolved)):
            logger.warning("Попытка удалить файл вне data_dir: %s", path)
            return
        self.delete_tree(path)


def _now_ts() -> float:
    import time

    return time.time()
