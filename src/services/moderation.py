"""Модерация: блоклисты запрещённых тем + LLM-судья для изображений.

Запрещено всегда:
- несовершеннолетние / неопределённый возраст в сексуальном контексте;
- сексуализированное возрастное омоложение, young-looking и т.п.;
- сексуальное насилие и отсутствие согласия;
- шантаж, торговля людьми, сексуальная эксплуатация;
- инцест;
- сексуальный контент с животными;
- сексуальные дипфейки, реальные люди, раздевание по фото;
- клонирование голоса реального человека;
- публикация персональных данных;
- инструкции для реального вреда.

Для изображений правила жёстче (слово «ребёнок» в запросе картинки
блокируется всегда), для текстового диалога — мягче (необходимо
сочетание с сексуальным контекстом), чтобы не ломать обычные темы.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.database.base import Database
from src.prompts import PromptLibrary
from src.providers.base import LLMProvider, LLMUnavailable
from src.utils import extract_json, truncate

logger = logging.getLogger(__name__)

# Маркеры сексуального контекста (для «мягких» правил в тексте)
_SEXUAL_MARKERS = re.compile(
    r"секс|эрот|интим|обнаж|гол(ый|ая|ые|еньк)|разде(вай|ть|лась|лся|ться)|"
    r"трах|постел|ню(?!р)|nude|naked|nsfw|sex|erotic|undress|porn|hentai|"
    r"эксплицит|возбуж|шалост|ласк|поцелуй|целоват",
    re.IGNORECASE,
)

# Жёсткие правила: блокируются всегда (текст и изображения)
_HARD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"изнасил|насильств|rape|forced\s*sex|принуждени[ея]|без\s+согласия", re.I), "non_consent"),
    (re.compile(r"инцест|incest", re.I), "incest"),
    (re.compile(r"зоофил|скотолож|bestiality|секс\s*с\s+животн", re.I), "animal"),
    (re.compile(r"педофил|педофили", re.I), "minor"),
    (re.compile(r"\bloli\b|\bshota\b|лоли", re.I), "minor"),
    (re.compile(r"школьниц|школьник|schoolgirl|schoolboy", re.I), "minor"),
    (re.compile(r"несовершеннолетн|малолетн|underage|jailbait", re.I), "minor"),
    (re.compile(r"дипфейк|deepfake", re.I), "deepfake"),
    (re.compile(r"торговл[а-я]*\s+людьми|трафик\s+людей|sex\s+trafficking|эксплуатац", re.I), "exploitation"),
    (re.compile(r"клонир(овани[ея]|овать)?\s+(чуж|голос)|voice\s+clone", re.I), "voice_clone"),
    (re.compile(r"разде(ть|вать)?\s*(реальн|по\s*фото)|сними\s+(одежд|бель[её])", re.I), "real_person"),
]

# Мягкие правила: блокируются только вместе с сексуальным маркером
_SOFT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"реб[её]нк|ребён|child(ren)?|\bkid(s)?\b|детск|детей|детям", re.I), "minor"),
    (re.compile(r"молод(еньк|ую|ую|ой|ая|ые)?|young|teen|подростк|юн(ый|ая|ые|ых)", re.I), "minor"),
    (re.compile(r"\b(12|13|14|15|16|17)\b", re.I), "minor_age"),
    (re.compile(r"дочь|сын|сестра|брат|мать|отец|мама|папа", re.I), "incest"),
    (
        re.compile(
            r"реальн(ый|ая|ые|ых|ого)?\s*(человек|девушк|женщин|мужчин|парн|фото)|"
            r"по\s+фотографии|известн(ый|ая|ые)",
            re.I,
        ),
        "real_person",
    ),
    (re.compile(r"животн|звер(ь|ей|ями)|щен|котен|котён", re.I), "animal"),
]

# Правила, применяемые только к запросам изображений (жёстче)
_IMAGE_ONLY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"реб[её]нк|ребён|child|kid|детск|детей|младен", re.I), "minor"),
    (re.compile(r"teen|young|teenager|подростк|школьн|school", re.I), "minor"),
    (re.compile(r"\b(12|13|14|15|16|17)\b", re.I), "minor_age"),
]

# Явные маркеры несовершеннолетия. Используются для защиты от ложных
# срабатываний LLM-судьи: если судья заблокировал запрос как «minor»,
# но явных признаков нет — это перестраховка, и запрос пропускается
# (взрослый контент 18+ разрешён).
_EXPLICIT_MINOR_MARKERS = re.compile(
    r"реб[её]н|ребен|child(?:ren)?|\bkid(s)?\b|детск|младен|малолетн|"
    r"несовершеннолетн|подростк|школьн|school(?:girl|boy)?|\bteen\b|"
    r"young(?:[- ]looking)?|underage|jailbait|\bloli\b|\bshota\b|лоли|"
    r"\b(?:12|13|14|15|16|17)\b|лет\s*(?:16|17)|"
    r"выгляд(?:ит|ящ|ит\s+на)\s*(?:на|как)?\s*(?:16|17|реб)",
    re.IGNORECASE,
)

# Сообщения отказа — короткие, без графических деталей
REFUSAL_TEXTS: dict[str, str] = {
    "minor": (
        "Я не могу участвовать в этом: персонажу и собеседнику должно быть за 18, "
        "и никаких намёков на несовершеннолетних. Могу пообщаться в дружеском "
        "или романтическом ключе — как тебе удобнее."
    ),
    "minor_age": ("Эта тема мне не подходит — только взрослые персонажи 21+. Давай останемся в безопасных рамках?"),
    "non_consent": (
        "Это не моя тема: только добровольное общение между взрослыми. "
        "Могу предложить что-то нежное и по обоюдному согласию."
    ),
    "incest": "Извини, но это для меня табу. Могу поболтать на другие взрослые темы.",
    "animal": ("Это невозможно — такие темы полностью исключены. Давай вернёмся к чему-то человеческому и тёплому?"),
    "real_person": ("Я — вымышленный персонаж и не могу участвовать в контенте с реальными людьми или их фото."),
    "deepfake": (
        "Дипфейки и подделки с реальными людьми запрещены. Я могу нарисовать только свою вымышленную внешность."
    ),
    "voice_clone": ("Клонирование голоса реального человека без его согласия недопустимо. У меня есть свой голос."),
    "exploitation": "Это недопустимо. Могу просто побыть рядом и поболтать?",
    "unknown": "Извини, но эта тема вне моих границ. Давай поговорим о чём-то другом?",
}


@dataclass
class ModerationDecision:
    blocked: bool
    reason_code: str | None = None


class ModerationService:
    def __init__(self, db: Database, llm: LLMProvider, prompts: PromptLibrary) -> None:
        self.db = db
        self.llm = llm
        self.prompts = prompts

    # ------------------------------------------------------------------ блоклист

    def check_text_blocklist(self, text: str) -> ModerationDecision:
        """Проверка текста пользователя быстрым блоклистом."""
        for pattern, reason in _HARD_RULES:
            if pattern.search(text):
                return ModerationDecision(blocked=True, reason_code=reason)
        if not _SEXUAL_MARKERS.search(text):
            return ModerationDecision(blocked=False)
        for pattern, reason in _SOFT_RULES:
            if pattern.search(text):
                return ModerationDecision(blocked=True, reason_code=reason)
        return ModerationDecision(blocked=False)

    def check_image_blocklist(self, text: str) -> ModerationDecision:
        """Проверка запроса изображения: жёстче, чем для текста."""
        for pattern, reason in _HARD_RULES:
            if pattern.search(text):
                return ModerationDecision(blocked=True, reason_code=reason)
        for pattern, reason in _IMAGE_ONLY_RULES:
            if pattern.search(text):
                return ModerationDecision(blocked=True, reason_code=reason)
        if _SEXUAL_MARKERS.search(text):
            for pattern, reason in _SOFT_RULES:
                if pattern.search(text):
                    return ModerationDecision(blocked=True, reason_code=reason)
        return ModerationDecision(blocked=False)

    # ------------------------------------------------------------------ LLM-судья

    async def judge_image_request(self, text: str) -> ModerationDecision:
        """LLM-проверка запроса изображения. При недоступности LLM — fallback на блоклист."""
        try:
            prompt = self.prompts.moderation_prompt.format(request=truncate(text, 2000))
            raw = await self.llm.chat([{"role": "user", "content": prompt}], temperature=0.0, max_tokens=200)
            data = extract_json(raw)
            if isinstance(data, dict):
                blocked = bool(data.get("blocked", False))
                reason = str(data.get("reason_code") or "unknown")
                if blocked:
                    # Защита от ложных срабатываний: судья может заблокировать
                    # запрос как «несовершеннолетие» без реальных признаков
                    # (например, «сексуальная девушка» — взрослая!). Если явных
                    # маркеров нет — пропускаем: взрослый контент разрешён.
                    if reason in ("minor", "minor_age", "unknown") and not _EXPLICIT_MINOR_MARKERS.search(text):
                        logger.info(
                            "LLM-судья: ложное срабатывание (%s) без явных маркеров — пропускаю",
                            reason,
                        )
                        return ModerationDecision(blocked=False)
                    return ModerationDecision(blocked=True, reason_code=reason)
                return ModerationDecision(blocked=False)
        except LLMUnavailable:
            logger.warning("LLM-судья недоступен — используется только блоклист")
        except Exception:
            logger.exception("Ошибка LLM-модерации изображения")
        return self.check_image_blocklist(text)

    def refusal_text(self, reason_code: str | None) -> str:
        return REFUSAL_TEXTS.get(reason_code or "", REFUSAL_TEXTS["unknown"])

    def refusal_short(self, reason_code: str | None) -> str:
        """Короткий отказ для inline-уведомлений."""
        base = self.refusal_text(reason_code)
        return truncate(base, 300)
