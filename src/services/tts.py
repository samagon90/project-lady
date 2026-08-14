"""Сервис голосовых сообщений: TTS -> WAV -> OGG/Opus -> временный файл.

Если TTS недоступен, текстовый ответ всё равно должен быть отправлен —
это ответственность вызывающего кода (хендлера).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from src.config import Settings
from src.providers.base import TTSProvider, TTSUnavailable
from src.services.storage import StorageService
from src.utils import chunk_text, strip_markdown, truncate

logger = logging.getLogger(__name__)

_MAX_VOICE_CHARS = 1500


class AudioConverter(Protocol):
    async def convert(self, wav_paths: list[Path], out_ogg: Path) -> None: ...


class FFmpegAudioConverter:
    """Конвертация WAV в OGG/Opus через ffmpeg (формат голосовых Telegram)."""

    def __init__(self, ffmpeg_binary: str = "ffmpeg", timeout: float = 60.0) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self.timeout = timeout

    async def convert(self, wav_paths: list[Path], out_ogg: Path) -> None:
        if not wav_paths:
            raise TTSUnavailable("Нет аудио для конвертации")
        try:
            if len(wav_paths) == 1:
                cmd = [
                    self.ffmpeg_binary,
                    "-y",
                    "-i",
                    str(wav_paths[0]),
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "32k",
                    "-ar",
                    "48000",
                    "-f",
                    "ogg",
                    str(out_ogg),
                ]
            else:
                list_file = out_ogg.with_suffix(".txt")
                list_file.write_text(
                    "\n".join(f"file '{path.as_posix()}'" for path in wav_paths),
                    encoding="utf-8",
                )
                cmd = [
                    self.ffmpeg_binary,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_file),
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "32k",
                    "-ar",
                    "48000",
                    "-f",
                    "ogg",
                    str(out_ogg),
                ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            if process.returncode != 0:
                logger.warning("ffmpeg: %s", stderr.decode(errors="replace")[:300])
                raise TTSUnavailable("ffmpeg не смог конвертировать аудио")
        except FileNotFoundError as exc:
            raise TTSUnavailable("ffmpeg не установлен") from exc
        except TimeoutError as exc:
            raise TTSUnavailable("ffmpeg превысил таймаут") from exc


class TTSService:
    """Синтез речи: очистка текста, разбиение на части, Piper, конвертация."""

    def __init__(
        self,
        provider: TTSProvider,
        settings: Settings,
        storage: StorageService,
        converter: AudioConverter | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.storage = storage
        self.converter = converter or FFmpegAudioConverter()

    async def build_voice(self, text: str, *, speed: float = 1.0) -> Path | None:
        """Создаёт OGG/Opus файл. Возвращает None при любой ошибке (fallback)."""
        if not self.settings.tts_enabled:
            return None
        cleaned = strip_markdown(text)
        cleaned = truncate(cleaned, _MAX_VOICE_CHARS)
        if not cleaned:
            return None
        chunks = chunk_text(cleaned, self.settings.tts_max_chars)
        if not chunks:
            return None
        wav_paths: list[Path] = []
        try:
            for chunk in chunks:
                wav = self.storage.new_temp_path("voice", ".wav")
                try:
                    await self.provider.synthesize(chunk, wav, speed=speed)
                except TTSUnavailable:
                    logger.warning("TTS недоступен — голосовое пропущено")
                    return None
                if not wav.exists() or wav.stat().st_size == 0:
                    logger.warning("TTS вернул пустой файл — голосовое пропущено")
                    return None
                wav_paths.append(wav)
            ogg = self.storage.new_temp_path("voice", ".ogg")
            try:
                await self.converter.convert(wav_paths, ogg)
            except TTSUnavailable:
                logger.warning("Конвертация аудио не удалась — голосовое пропущено")
                return None
            if not ogg.exists() or ogg.stat().st_size == 0:
                return None
            return ogg
        finally:
            self.storage.remove_many(wav_paths)
