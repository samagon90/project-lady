"""Провайдер TTS через Piper (бесплатный, open source, работает локально).

Piper — нейросетевой TTS, голоса распространяются под свободными лицензиями.
Голоса реальных людей не клонируются; используются только публичные голоса
с подтверждённым согласием авторов (например, ru_RU-irina-medium).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from src.providers.base import TTSUnavailable

logger = logging.getLogger(__name__)


class PiperTTSProvider:
    def __init__(
        self,
        binary: str = "piper",
        voice_model: Path | None = None,
        voice_config: Path | None = None,
        *,
        length_scale: float = 1.0,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.binary = binary
        self.voice_model = voice_model
        self.voice_config = voice_config
        self.length_scale = length_scale
        self.timeout = timeout_seconds

    async def synthesize(self, text: str, out_path: Path, *, speed: float = 1.0) -> None:
        if not self._available():
            raise TTSUnavailable("Piper не установлен или голосовая модель не найдена")
        cmd = [self.binary, "--output_file", str(out_path)]
        if self.voice_model is not None:
            cmd += ["--model", str(self.voice_model)]
        if self.voice_config is not None:
            cmd += ["--config", str(self.voice_config)]
        # speed > 1 → быстрее → length_scale меньше
        effective_scale = max(0.2, self.length_scale / max(speed, 0.1))
        cmd += ["--length-scale", f"{effective_scale:.3f}"]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise TTSUnavailable("Исполняемый файл piper не найден") from exc
        try:
            _, stderr = await asyncio.wait_for(process.communicate(input=text.encode("utf-8")), timeout=self.timeout)
        except TimeoutError as exc:
            process.kill()
            raise TTSUnavailable("Piper превысил таймаут синтеза") from exc
        if process.returncode != 0:
            logger.warning("Piper завершился с кодом %s", process.returncode)
            raise TTSUnavailable("Piper не смог синтезировать речь")

    def _available(self) -> bool:
        if shutil.which(self.binary) is None:
            return False
        if self.voice_model is not None and not self.voice_model.exists():
            return False
        return True

    async def health(self) -> bool:
        return self._available()
