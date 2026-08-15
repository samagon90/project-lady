"""Тесты облачных провайдеров LLM (OpenRouter / Venice)."""
from __future__ import annotations

from src.providers.base import LLMUnavailable
from src.providers.openrouter import OpenAICompatLLMProvider


async def test_openrouter_chat(monkeypatch) -> None:
    """Провайдер шлёт OpenAI-формат и разбирает ответ."""
    async def fake_post(url, json=None, headers=None):
        class R:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "Привет, мой дорогой"}}]}

            @property
            def text(self):
                return ""

        return R()

    provider = OpenAICompatLLMProvider(
        "https://openrouter.ai/api/v1", "test-key", "openrouter/free"
    )
    async def client():
        return _FakeClient(fake_post)

    monkeypatch.setattr(provider, "_client_instance", client)
    reply = await provider.chat([{"role": "user", "content": "привет"}])
    assert reply == "Привет, мой дорогой"


async def test_openrouter_unauthorized(monkeypatch) -> None:
    async def fake_post(url, json=None, headers=None):
        class R:
            status_code = 401
            text = "unauthorized"

            def json(self):
                return {}

        return R()

    provider = OpenAICompatLLMProvider(
        "https://openrouter.ai/api/v1", "bad-key", "openrouter/free"
    )
    async def client():
        return _FakeClient(fake_post)

    monkeypatch.setattr(provider, "_client_instance", client)
    try:
        await provider.chat([{"role": "user", "content": "hi"}])
        raise AssertionError("должна быть ошибка")
    except LLMUnavailable as exc:
        assert "401" in str(exc)


async def test_openrouter_rate_limit(monkeypatch) -> None:
    async def fake_post(url, json=None, headers=None):
        class R:
            status_code = 429
            text = "rate limited"

            def json(self):
                return {}

        return R()

    provider = OpenAICompatLLMProvider(
        "https://openrouter.ai/api/v1", "k", "openrouter/free", retries=0
    )
    async def client():
        return _FakeClient(fake_post)

    monkeypatch.setattr(provider, "_client_instance", client)
    try:
        await provider.chat([{"role": "user", "content": "hi"}])
        raise AssertionError("должна быть ошибка")
    except LLMUnavailable as exc:
        assert "429" in str(exc)


class _FakeClient:
    def __init__(self, fake_post):
        self._fake_post = fake_post

    async def post(self, url, json=None, headers=None):
        return await self._fake_post(url, json=json, headers=headers)


# ---------------------------------------------------------------------------
# Ollama-провайдер: embeddings отдельной моделью + авто-выбор модели
# ---------------------------------------------------------------------------

from src.providers.ollama import OllamaLLMProvider  # noqa: E402


async def test_ollama_embed_uses_embed_model() -> None:
    """Embeddings должны ходить ОТДЕЛЬНОЙ моделью (nomic-embed-text),
    а не чат-моделью — иначе Ollama отвечает 400 «does not support embeddings»
    и семантическая память падает."""
    seen: dict = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"embeddings": [[0.1, 0.2, 0.3]]}

    class FakeClient:
        async def post(self, url, json=None):
            seen["url"] = url
            seen["model"] = json["model"]
            return FakeResp()

        async def get(self, url, **kwargs):
            return FakeResp()

    provider = OllamaLLMProvider(
        "http://127.0.0.1:11434",
        "huihui_ai/qwen3-abliterated:14b",
        embed_model="nomic-embed-text",
        client=FakeClient(),  # type: ignore[arg-type]
    )
    vecs = await provider.embed(["привет"])
    assert seen["url"] == "http://127.0.0.1:11434/api/embed"
    assert seen["model"] == "nomic-embed-text"
    assert vecs == [[0.1, 0.2, 0.3]]


async def test_ollama_embed_fallback_uses_embed_model() -> None:
    """Fallback /api/embeddings тоже использует embed_model."""
    seen: dict = {}

    class FakeResp400:
        status_code = 400

        def json(self):
            return {}

    class FakeResp200:
        status_code = 200

        def json(self):
            return {"embedding": [0.5, 0.6]}

    class FakeClient:
        async def post(self, url, json=None):
            if url.endswith("/api/embed"):
                seen["embed_model"] = json["model"]
                return FakeResp400()
            seen["embeddings_model"] = json["model"]
            return FakeResp200()

        async def get(self, url, **kwargs):
            return FakeResp200()

    provider = OllamaLLMProvider(
        "http://127.0.0.1:11434",
        "qwen2.5:7b",
        embed_model="nomic-embed-text",
        client=FakeClient(),  # type: ignore[arg-type]
    )
    vecs = await provider.embed(["факт"])
    assert seen["embed_model"] == "nomic-embed-text"
    assert seen["embeddings_model"] == "nomic-embed-text"
    assert vecs == [[0.5, 0.6]]


async def test_ollama_auto_pick_model() -> None:
    """Если LLM_MODEL в .env не та, что установлена, — бот сам выбирает
    рабочую модель (лечит старые ноутбуки без LLM_MODEL)."""

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {"name": "nomic-embed-text"},
                    {"name": "huihui_ai/qwen3-abliterated:14b"},
                ]
            }

    class FakeClient:
        async def get(self, url, **kwargs):
            return FakeResp()

    # Модель из .env отсутствует — подбираем из preferred
    provider = OllamaLLMProvider(
        "http://127.0.0.1:11434",
        "qwen2.5:7b",
        client=FakeClient(),  # type: ignore[arg-type]
    )
    chosen = await provider.auto_pick_model(preferred=("huihui_ai/qwen3-abliterated",))
    assert chosen == "huihui_ai/qwen3-abliterated:14b"
    assert provider.model == chosen

    # Модель уже установлена — ничего не меняем
    provider2 = OllamaLLMProvider(
        "http://127.0.0.1:11434",
        "huihui_ai/qwen3-abliterated:14b",
        client=FakeClient(),  # type: ignore[arg-type]
    )
    assert await provider2.auto_pick_model() == "huihui_ai/qwen3-abliterated:14b"

    # Ollama выключена — оставляем как есть
    class DeadClient:
        async def get(self, url, **kwargs):
            raise OSError("connection refused")

    provider3 = OllamaLLMProvider(
        "http://127.0.0.1:11434",
        "qwen2.5:7b",
        client=DeadClient(),  # type: ignore[arg-type]
    )
    assert await provider3.auto_pick_model() == "qwen2.5:7b"


async def test_ollama_health_checks_model_presence() -> None:
    """health() = Ollama жива И нужная модель установлена."""

    class FakeResp:
        status_code = 200

        def json(self):
            return {"models": [{"name": "nomic-embed-text"}, {"name": "qwen2.5:7b"}]}

    class FakeClient:
        async def get(self, url, **kwargs):
            return FakeResp()

    ok = OllamaLLMProvider(
        "http://127.0.0.1:11434",
        "qwen2.5:7b",
        client=FakeClient(),  # type: ignore[arg-type]
    )
    assert await ok.health() is True

    missing = OllamaLLMProvider(
        "http://127.0.0.1:11434",
        "huihui_ai/qwen3-abliterated:14b",
        client=FakeClient(),  # type: ignore[arg-type]
    )
    assert await missing.health() is False


async def test_openrouter_embed_graceful() -> None:
    """Облачный провайдер не умеет embeddings — должен мягко сообщить
    (LLMUnavailable), а не падать с AttributeError."""
    provider = OpenAICompatLLMProvider(
        "https://openrouter.ai/api/v1", "test-key", "openrouter/free"
    )
    try:
        await provider.embed(["факт"])
        raise AssertionError("должна быть ошибка")
    except LLMUnavailable as exc:
        assert "Embeddings" in str(exc)
    # пустой список — без ошибок
    assert await provider.embed([]) == []
