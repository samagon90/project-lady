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
