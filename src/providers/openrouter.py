"""Провайдер LLM через OpenAI-совместимые облачные API.

Покрывает:
- OpenRouter (openrouter.ai) — хаб моделей, включая NSFW-дружественные
  от провайдеров DeepInfra / Novita / Together (фильтр через OPENROUTER_PROVIDERS);
- Venice (api.venice.ai) — самый либеральный NSFW-провайдер.

Оба используют единый OpenAI-формат: POST /chat/completions.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from src.providers.base import LLMUnavailable

logger = logging.getLogger(__name__)


class OpenAICompatLLMProvider:
    """Клиент OpenAI-совместимого API (OpenRouter / Venice и др.)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        temperature: float = 0.8,
        timeout_seconds: float = 120.0,
        retries: int = 2,
        extra_headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout_seconds
        self.retries = retries
        self.extra_headers = extra_headers or {}
        self._client = client
        self._owns_client = client is None

    async def _client_instance(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.api_key:
            raise LLMUnavailable("API-ключ не задан (OPENROUTER_API_KEY / VENICE_API_KEY)")
        client = await self._client_instance()
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                if response.status_code == 401:
                    raise LLMUnavailable("Неверный API-ключ (401)")
                if response.status_code == 429:
                    raise LLMUnavailable(
                        "Превышен лимит запросов (429). Бесплатные модели OpenRouter: "
                        "50 запросов/день, 20/мин. Подождите или смените модель."
                    )
                if response.status_code == 402:
                    raise LLMUnavailable(
                        "Требуется пополнение баланса (402) — бесплатные модели "
                        "могут требовать $10 кредита для повышения лимита."
                    )
                if response.status_code >= 400:
                    raise LLMUnavailable(
                        f"API вернул HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                data = response.json()
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                if not content:
                    raise LLMUnavailable("API вернул пустой ответ")
                return str(content)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                last_error = exc
                logger.warning("API недоступен (попытка %s): %s", attempt + 1, exc)
                if attempt < self.retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise LLMUnavailable(f"Облачный LLM недоступен: {self.base_url}") from last_error

    async def health(self) -> bool:
        if not self.api_key:
            return False
        try:
            client = await self._client_instance()
            response = await client.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10.0,
            )
            return response.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def __repr__(self) -> str:  # для логов — без ключей
        return f"OpenAICompatLLMProvider(model={self.model}, url={self.base_url})"
