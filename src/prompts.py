"""Загрузка системных промптов из файлов (папка prompts/)."""

from __future__ import annotations

from pathlib import Path

from src.config import PROJECT_ROOT, Settings
from src.database.models import User

MODE_LABELS = {0: "дружеский", 1: "лёгкий флирт", 2: "романтический", 3: "NSFW"}

_MODE_INSTRUCTIONS = {
    0: ("Дружеский режим: общайся тепло, с юмором и по-дружески. Никакого флирта и романтики."),
    1: ("Режим лёгкого флирта: игривые комплименты, лёгкая кокетливость, намёки. Без откровенных и сексуальных тем."),
    2: ("Романтический режим: нежные, тёплые, эмоционально близкие ответы. Откровенный сексуальный контент запрещён."),
    3: (
        "NSFW-режим: пользователь дал отдельное добровольное согласие, ему есть 18+. "
        "Взрослый эротический диалог допустим, но только по желанию пользователя, "
        "без давления. Строго запрещены: несовершеннолетние и неопределённый возраст, "
        "насилие и принуждение, инцест, животные, реальные люди и дипфейки, "
        "эксплуатация и шантаж. При любом запрещённом запросе коротко откажи "
        "и предложи безопасную взрослую альтернативу."
    ),
}


class PromptLibrary:
    """Контейнер промптов. Все тексты лежат в файлах проекта."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.dir = (prompts_dir or (PROJECT_ROOT / "prompts")).resolve()
        self.persona = self._load("persona_leya.md")
        self.system_template = self._load("system.md")
        self.safety_rules = self._load("safety_rules.md")
        self.extraction_prompt = self._load("extract_facts.md")
        self.summarization_prompt = self._load("summarize.md")
        self.image_prompt_prompt = self._load("image_prompt.md")
        self.moderation_prompt = self._load("moderation.md")
        self.character_sheet = self._load("character_sheet.md")
        self.default_negative_prompt = (
            "worst quality, low quality, bad anatomy, bad hands, extra fingers, "
            "deformed, watermark, text, signature, photo of real person, celebrity, "
            "minor, child, underage"
        )

    def _load(self, name: str) -> str:
        path = self.dir / name
        if not path.exists():
            raise FileNotFoundError(f"Файл промпта не найден: {path}")
        return path.read_text(encoding="utf-8").strip()

    # ------------------------------------------------------------------ сборка

    def system_prompt(self, user: User, ctx) -> str:
        """Системный промпт: персонаж + режим + правила."""
        mode = min(max(ctx.mode, 0), 3)
        return self.system_template.format(
            persona=self.persona,
            mode=_MODE_INSTRUCTIONS[mode],
            safety=self.safety_rules,
            mode_label=MODE_LABELS[mode],
        )


def load_prompt_library(settings: Settings | None = None) -> PromptLibrary:
    return PromptLibrary()
