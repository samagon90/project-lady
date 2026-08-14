"""Абстрактные интерфейсы провайдеров и общие типы.

Бизнес-логика зависит только от этих протоколов, поэтому любую модель
можно заменить через переменные окружения (или DI в тестах).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class LLMError(Exception):
    """Базовая ошибка LLM."""


class LLMUnavailable(LLMError):
    """Модель недоступна (Ollama не запущен, таймаут, сеть)."""


class LLMOutputError(LLMError):
    """Модель ответила, но ответ нечитаем (нет JSON и т.п.)."""


class LLMProvider(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str: ...

    async def health(self) -> bool: ...


class EmbeddingsProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def health(self) -> bool: ...


class ImageProviderError(Exception):
    """Базовая ошибка генератора изображений."""


class ImageProviderUnavailable(ImageProviderError):
    """ComfyUI недоступен (не запущен, таймаут, сеть)."""


class ImageProvider(Protocol):
    async def generate(self, request: ImageRequest) -> list[bytes]: ...

    async def health(self) -> bool: ...


class TTSError(Exception):
    """Базовая ошибка TTS."""


class TTSUnavailable(TTSError):
    """TTS недоступен (piper не установлен, нет голоса)."""


class TTSProvider(Protocol):
    async def synthesize(self, text: str, out_path: Path, *, speed: float = 1.0) -> None: ...

    async def health(self) -> bool: ...


@dataclass
class ImageRequest:
    """Структурированный запрос к генератору изображений (результат LLM)."""

    prompt: str
    negative_prompt: str = ""
    width: int = 512
    height: int = 768
    steps: int = 28
    cfg: float = 7.0
    seed: int = -1
    nsfw: bool = False

    def __post_init__(self) -> None:
        self.width = max(256, min(1536, self.width // 8 * 8))
        self.height = max(256, min(1536, self.height // 8 * 8))
        self.steps = max(1, min(60, int(self.steps)))
        self.cfg = max(1.0, min(30.0, float(self.cfg)))
        if self.seed == -1:
            self.seed = _random_seed()


def _random_seed() -> int:
    import random

    return random.randint(0, 2**32 - 1)
