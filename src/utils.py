"""Общие утилиты: время, JSON, безопасные имена файлов, текст."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path


def utcnow() -> datetime:
    """Наивный UTC-now (единый формат для SQLite и PostgreSQL)."""
    return datetime.now(UTC).replace(tzinfo=None)


def new_uuid() -> str:
    return uuid.uuid4().hex


def safe_filename(prefix: str, suffix: str) -> str:
    """Безопасное имя временного файла: только uuid, без пользовательского ввода."""
    return f"{prefix}_{new_uuid()}{suffix}"


def extract_json(text: str) -> object:
    """Достаёт JSON из ответа LLM: сначала полный парсинг, затем первый JSON-блок."""
    text = text.strip()
    if not text:
        raise ValueError("Пустой ответ модели")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError("В ответе модели нет корректного JSON")


def strip_markdown(text: str) -> str:
    """Очищает текст от Markdown/HTML-разметки и технических символов для TTS."""
    text = re.sub(r"[*_`#~>|\[\]()]", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\\n", " ").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"https?://\S+", "ссылка", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Делит текст на части по границам предложений, не превышая max_chars."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        if len(sentence) > max_chars:
            # одно гигантское «предложение» — режем по запятым и пробелам
            for piece in _hard_split(sentence, max_chars):
                if current and len(current) + len(piece) + 1 > max_chars:
                    chunks.append(current.strip())
                    current = ""
                current = (current + " " + piece).strip()
            continue
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip()
    if current:
        chunks.append(current.strip())
    return chunks


def _hard_split(text: str, max_chars: int) -> list[str]:
    words = text.split()
    parts: list[str] = []
    buf = ""
    for word in words:
        while len(word) > max_chars:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(word[:max_chars])
            word = word[max_chars:]
        if buf and len(buf) + len(word) + 1 > max_chars:
            parts.append(buf)
            buf = word
        else:
            buf = (buf + " " + word).strip()
    if buf:
        parts.append(buf)
    return parts


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def age_seconds(then: datetime) -> float:
    return (utcnow() - then).total_seconds()


def is_expired(then: datetime | None, ttl: timedelta) -> bool:
    if then is None:
        return False
    return age_seconds(then) > ttl.total_seconds()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sanitize_log_value(value: str, max_len: int = 64) -> str:
    """Для логов: без содержимого переписки, только короткие обезличенные значения."""
    return truncate(value.replace("\n", " "), max_len)
