"""Фикстуры: настройки, фейковые провайдеры, бот, контекст, фабрики Update."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser

from src.bot.di import AppContext, build_app_context
from src.bot.handlers import router as handlers_router
from src.bot.middlewares import (
    ChatTypeMiddleware,
    ContextMiddleware,
    RateLimitMiddleware,
    RegistrationMiddleware,
)
from src.config import Settings
from src.database.models import Base
from src.providers.base import (
    LLMUnavailable,
    TTSUnavailable,
)
from src.services.tts import TTSService

# ===================================================================== фейки


class FakeLLM:
    """LLM с маршрутизацией по маркерам промптов.

    - модерация -> {"blocked": false}
    - извлечение фактов -> self.extraction_facts (JSON-строка или список)
    - image prompt -> self.image_prompt (dict)
    - иначе -> self.default_reply (или echo памяти, если echo_memory=True)
    """

    def __init__(
        self,
        *,
        default_reply: str = "Привет!",
        extraction_facts: list[dict] | None = None,
        image_prompt: dict | None = None,
        echo_memory: bool = False,
        fail: bool = False,
        chinese_first: bool = False,
        chinese_only: bool = False,
    ) -> None:
        self.default_reply = default_reply
        self.extraction_facts = extraction_facts or []
        self.image_prompt = image_prompt or {
            "prompt": "Lilith in a park, digital art",
            "negative_prompt": "worst quality",
            "width": 512,
            "height": 768,
            "steps": 28,
            "cfg": 7.0,
            "seed": -1,
            "nsfw": False,
        }
        self.echo_memory = echo_memory
        self.fail = fail
        self.fix_reply = None  # если задан — возвращается при повторном вызове (переспросе)
        self.chinese_first = chinese_first
        self.chinese_only = chinese_only
        # Имитация строгого LLM-судьи: если задано — возвращает этот JSON
        # для запросов модерации (например, {"blocked": true, "reason_code": "minor"})
        self.judge_blocked: dict | None = None
        self.calls: list[list[dict[str, str]]] = []

    def _maybe_chinese(self) -> str | None:
        """Симуляция глючной модели, отвечающей иероглифами."""
        if self.chinese_only:
            return "判断过程中，我将用户请求与提供的答案进行了匹配。"
        if self.chinese_first and len(self.calls) <= 1:
            return "判断过程中，我将用户请求与提供的答案进行了匹配。"
        return None

    async def chat(self, messages, *, temperature=None, max_tokens=None) -> str:
        self.calls.append(messages)
        if self.fail:
            raise LLMUnavailable("ollama down")
        chinese = self._maybe_chinese()
        if chinese is not None:
            return chinese
        # Если задан fix_reply и это повторный вызов (переспрос) — возвращаем его
        if self.fix_reply is not None and len(self.calls) > 1:
            last_user = messages[-1]["content"] if messages else ""
            if "Перепиши свой ответ" in last_user or "Отвечай СТРОГО" in last_user:
                return self.fix_reply
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "модератор контента" in last_user:
            if self.judge_blocked is not None:
                import json

                return json.dumps(self.judge_blocked, ensure_ascii=False)
            return '{"blocked": false, "reason_code": "", "reason_text": ""}'
        if "модуль долговременной памяти" in last_user:
            import json

            return json.dumps(self.extraction_facts, ensure_ascii=False)
        if "модуль суммаризации" in last_user:
            return "Пользователь обсуждал свои интересы."
        if "модуль подготовки запросов" in last_user:
            import json

            return json.dumps(self.image_prompt, ensure_ascii=False)
        if self.echo_memory:
            memory = next(
                (m["content"] for m in messages if m["role"] == "system" and "Память и контекст" in m["content"]),
                "",
            )
            return memory or self.default_reply
        return self.default_reply

    async def health(self) -> bool:
        return True


class FakeEmbeddings:
    """Детерминированные векторы: одинаковый текст -> одинаковый вектор."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            vector = []
            for i in range(self.dim):
                h = hash((text, i)) % 1000
                vector.append(h / 1000.0)
            result.append(vector)
        return result

    async def health(self) -> bool:
        return True


class FakeImageProvider:
    def __init__(self, *, fail_with: Exception | None = None, images: list[bytes] | None = None) -> None:
        self.fail_with = fail_with
        self.images = images or [b"\x89PNG\r\nFAKEDATA"]
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return self.images

    async def health(self) -> bool:
        return self.fail_with is None


class FakeTTS:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def synthesize(self, text: str, out_path: Path, *, speed: float = 1.0) -> None:
        self.calls += 1
        if self.fail:
            raise TTSUnavailable("piper down")
        out_path.write_bytes(b"FAKEWAV")  # noqa: ASYNC240

    async def health(self) -> bool:
        return not self.fail


class FakeAudioConverter:
    async def convert(self, wav_paths: list[Path], out_ogg: Path) -> None:
        out_ogg.write_bytes(b"FAKEOPUS")  # noqa: ASYNC240


class FakeBot:
    """Минимальный бот для feed_update: записывает вызовы API."""

    def __init__(self) -> None:
        self.id = 1  # используется aiogram при логировании
        self.sent: list[tuple[str, int, dict]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> Message:
        self.sent.append(("message", chat_id, {"text": text, **kwargs}))
        return _fake_message(chat_id, text)

    async def send_voice(self, chat_id: int, voice, **kwargs) -> Message:
        self.sent.append(("voice", chat_id, {"voice": voice, **kwargs}))
        return _fake_message(chat_id, "voice")

    async def send_photo(self, chat_id: int, photo, **kwargs) -> Message:
        self.sent.append(("photo", chat_id, {"photo": photo, **kwargs}))
        return _fake_message(chat_id, "photo")

    async def answer_callback_query(self, callback_query_id: str, **kwargs) -> bool:
        self.sent.append(("answer_cb", 0, {"id": callback_query_id, **kwargs}))
        return True

    async def send_chat_action(self, chat_id: int, action: str, **kwargs) -> bool:
        return True

    async def get_me(self) -> TgUser:
        return TgUser(id=1, is_bot=True, first_name="Lilith Bot")

    def texts(self) -> list[str]:
        result = [item[2]["text"] for item in self.sent if item[0] == "message"]
        result += [item[2].get("caption", "") for item in self.sent if item[0] == "photo"]
        return result

    def last_text(self) -> str:
        return self.texts()[-1]


def _fake_message(chat_id: int, text: str) -> Message:
    user = TgUser(id=chat_id, is_bot=False, first_name="X")
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=user,
        text=text,
    )


# ===================================================================== фабрики Update

_MESSAGE_ID = [0]


def tg_user(uid: int, first_name: str = "User") -> TgUser:
    return TgUser(id=uid, is_bot=False, first_name=first_name)


def make_message(chat_id: int, user: TgUser, text: str, chat_type: str = "private") -> Message:
    _MESSAGE_ID[0] += 1
    return Message(
        message_id=_MESSAGE_ID[0],
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type=chat_type),
        from_user=user,
        text=text,
    )


def make_update_message(chat_id: int, user: TgUser, text: str, chat_type: str = "private") -> Update:
    return Update(update_id=_MESSAGE_ID[0], message=make_message(chat_id, user, text, chat_type))


def make_callback(chat_id: int, user: TgUser, data: str, message: Message | None = None) -> CallbackQuery:
    if message is None:
        message = make_message(chat_id, user, "button")
    return CallbackQuery(
        id=f"cb{_MESSAGE_ID[0]}",
        from_user=user,
        chat_instance=f"ci{_MESSAGE_ID[0]}",
        message=message,
        data=data,
    )


def make_update_callback(cb: CallbackQuery) -> Update:
    return Update(update_id=_MESSAGE_ID[0], callback_query=cb)


# ===================================================================== фикстуры


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        _env_file=None,
        telegram_token="test:token",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        data_dir=data_dir,
        temp_dir=data_dir / "tmp",
        log_file=None,
        piper_voice_model=Path("/nonexistent/voice.onnx"),
        comfyui_workflow_path=Path("workflows/comfyui_lilith_sd15.json"),
        rate_limit_messages_per_minute=100,
        memory_extract_every_n_messages=1,
        audit_enabled=True,
    )


@pytest.fixture
async def ctx(
    settings: Settings,
    fake_llm: FakeLLM,
    fake_embeddings: FakeEmbeddings,
    fake_image_provider: FakeImageProvider,
    fake_tts: FakeTTS,
) -> AppContext:
    context = build_app_context(
        settings,
        llm=fake_llm,
        embeddings_provider=fake_embeddings,
        image_provider=fake_image_provider,
        tts_provider=fake_tts,
    )
    await context.db.connect()
    async with context.db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    context.tts = TTSService(fake_tts, settings, context.storage, FakeAudioConverter())
    yield context
    await context.shutdown()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM(echo_memory=True)


@pytest.fixture
def fake_embeddings() -> FakeEmbeddings:
    return FakeEmbeddings(dim=768)


@pytest.fixture
def fake_image_provider() -> FakeImageProvider:
    return FakeImageProvider()


@pytest.fixture
def fake_tts() -> FakeTTS:
    return FakeTTS()


@pytest.fixture
def bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
async def dp(ctx: AppContext, settings: Settings, bot: FakeBot) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    for event_name in ("message", "callback_query"):
        mw = getattr(dispatcher, event_name).outer_middleware
        mw(ChatTypeMiddleware())
        mw(RateLimitMiddleware(settings))
        mw(ContextMiddleware(ctx))
        mw(RegistrationMiddleware(ctx))
    # Роутер-синглтон: разрешаем повторное прикрепление к свежему Dispatcher
    if handlers_router._parent_router is not None:  # noqa: SLF001
        handlers_router._parent_router = None  # noqa: SLF001
    dispatcher.include_router(handlers_router)
    return dispatcher


# ===================================================================== онбординг через сервисы


async def onboard(ctx: AppContext, telegram_user_id: int, *, nsfw: bool = True):
    """Полный онбординг пользователя (регистрация + согласия + активный статус)."""
    user = await ctx.consent.register(telegram_user_id, None, "User")
    await ctx.consent.accept_base(user)
    if nsfw:
        await ctx.consent.accept_nsfw(user)
    await ctx.consent.complete_onboarding(user)
    return user


async def drain_background(ctx: AppContext) -> None:
    """Дожидается фоновых задач чата (извлечение фактов и т.п.)."""
    tasks = list(ctx.chat.background_tasks)
    ctx.chat.background_tasks.clear()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
