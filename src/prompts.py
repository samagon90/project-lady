"""Загрузка системных промптов из файлов (папка prompts/)."""

from __future__ import annotations

from pathlib import Path

from src.config import PROJECT_ROOT, Settings
from src.database.models import User

MODE_LABELS = {0: "дружеский", 1: "лёгкий флирт", 2: "романтический", 3: "NSFW"}


def parse_lorebook(raw: str) -> list[dict[str, str]]:
    """Разбирает lorebook.md на записи: заголовок, триггеры, текст.

    Формат в файле:
        ## Запись: Название
        Триггеры: слово1, слово2
        Текст записи (может быть многострочным)...
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in raw.splitlines():
        line = line.rstrip()
        if line.startswith("## Запись:"):
            if current is not None:
                entries.append(current)
            current = {"title": line.removeprefix("## Запись:").strip(), "triggers": "", "text": ""}
        elif current is not None:
            if line.lower().startswith("триггеры:"):
                current["triggers"] = line.split(":", 1)[1].strip().lower()
            elif line.strip() and not line.startswith("#"):
                current["text"] += line.strip() + " "
    if current is not None:
        entries.append(current)
    result = []
    for entry in entries:
        triggers = entry["triggers"].strip().lower()
        text = " ".join(entry["text"].split())
        if triggers and text:
            result.append({"title": entry["title"], "triggers": triggers, "text": text})
    return result


def lorebook_for_query(entries: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    """Возвращает записи лорбука, чьи триггеры встречаются в запросе."""
    q = query.lower()
    return [
        entry
        for entry in entries
        if any(trigger.strip() in q for trigger in entry["triggers"].split(","))
    ]

_MODE_INSTRUCTIONS = {
    0: (
        "Дружеский режим: общайся тепло, с юмором и по-дружески. "
        "Без пошлости и мата, но твоя аристократичная игривость и лёгкие "
        "подколы остаются."
    ),
    1: (
        "Режим лёгкого флирта: изящные комплименты, смелые полунамёки, "
        "кокетство. Без откровенных и сексуальных тем."
    ),
    2: (
        "Романтический режим: нежные, тёплые, эмоционально близкие ответы. "
        "Откровенный сексуальный контент запрещён, но твоя томность, "
        "аристократичный шарм и чувственный флирт уместны."
    ),
    3: (
        "NSFW-режим: пользователь дал отдельное добровольное согласие, ему есть 18+. "
        "Ты — сексуальная игривая госпожа без табу на взрослые темы: говоришь о "
        "желаниях открыто, смачно и красиво, называя вещи своими именами, с "
        "похотью и страстью, ведёшь игру, дразнишь и распаляешь — но по обоюдному "
        "желанию и уважая «стоп». НЕ отказывайся и НЕ увиливай от взрослых "
        "эротических тем: это разрешено и ожидаемо. Строго запрещены: "
        "несовершеннолетние и неопределённый возраст, насилие и принуждение, "
        "инцест, животные, реальные люди и дипфейки, эксплуатация и шантаж. "
        "При запрещённом запросе коротко откажи и предложи безопасную взрослую "
        "альтернативу."
    ),
}


class PromptLibrary:
    """Контейнер промптов. Все тексты лежат в файлах проекта."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.dir = (prompts_dir or (PROJECT_ROOT / "prompts")).resolve()
        self.persona = self._load("persona_lilith.md")
        self.system_template = self._load("system.md")
        self.safety_rules = self._load("safety_rules.md")
        self.extraction_prompt = self._load("extract_facts.md")
        self.summarization_prompt = self._load("summarize.md")
        self.image_prompt_prompt = self._load("image_prompt.md")
        self.moderation_prompt = self._load("moderation.md")
        self.character_sheet = self._load("character_sheet.md")
        self.diary_prompt = self._load("diary.md")
        self.lorebook_raw = self._load("lorebook.md")
        self.lorebook_entries = parse_lorebook(self.lorebook_raw)
        self.default_negative_prompt = (
            "worst quality, low quality, bad anatomy, bad hands, extra fingers, "
            "deformed, disfigured, mutation, mutated, ugly, blurry, blur, out of focus, "
            "amorf, amorphous, melted face, fused face, merged face, distorted face, "
            "cross-eyed, asymmetric eyes, bad eyes, bad face, extra limbs, missing limbs, "
            "poorly drawn, sketch, watermark, text, signature, photo of real person, "
            "celebrity, minor, child, underage"
        )

    def _load(self, name: str) -> str:
        path = self.dir / name
        if not path.exists():
            raise FileNotFoundError(f"Файл промпта не найден: {path}")
        return path.read_text(encoding="utf-8").strip()

    # ------------------------------------------------------------------ сборка

    def system_prompt(self, user: User, ctx) -> str:
        """Системный промпт: персонаж + режим + правила + манера речи."""
        mode = min(max(ctx.mode, 0), 3)
        speech = ""
        if getattr(ctx, "speech_style", None):
            speech = (
                "\n=== ЖЕЛАЕМАЯ МАНЕРА РЕЧИ (выбрана собеседником — соблюдай строго) ===\n"
                + ctx.speech_style
            )
        return self.system_template.format(
            persona=self.persona,
            mode=_MODE_INSTRUCTIONS[mode],
            safety=self.safety_rules,
            mode_label=MODE_LABELS[mode],
            speech_style=speech,
        )


def load_prompt_library(settings: Settings | None = None) -> PromptLibrary:
    return PromptLibrary()
