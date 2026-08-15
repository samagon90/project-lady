"""Провайдер LLM и embeddings через локальный Ollama (бесплатный, open source).

Используется нативный HTTP API Ollama: /api/chat, /api/embed (fallback
/api/embeddings). Адрес и модель задаются через LLM_BASE_URL / LLM_MODEL.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from src.providers.base import LLMUnavailable

logger = logging.getLogger(__name__)


class OllamaLLMProvider:
    """Клиент Ollama с таймаутами, retry и понятными ошибками."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        embed_model: str | None = None,
        temperature: float = 0.8,
        timeout_seconds: float = 120.0,
        retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        # Отдельная модель для embeddings (например, nomic-embed-text).
        # Раньше для векторов использовалась чат-модель, а Ollama отвечает
        # 400 "does not support embeddings" — семантическая память падала.
        self.embed_model = embed_model or model
        self.temperature = temperature
        self.timeout = timeout_seconds
        self.retries = retries
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
        client = await self._client_instance()
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else self.temperature,
            },
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                if response.status_code == 404:
                    raise LLMUnavailable(
                        f"Модель '{self.model}' не найдена в Ollama. Выполните: ollama pull {self.model}"
                    )
                if response.status_code >= 400:
                    raise LLMUnavailable(f"Ollama вернул HTTP {response.status_code} для /api/chat")
                # Явно декодируем ответ как UTF-8: это гарантирует, что русский
                # текст не превратится в «иероглифы» из-за неверной кодировки.
                try:
                    data = response.json()
                except Exception as exc:  # noqa: BLE001
                    raw = response.content.decode("utf-8", errors="replace")
                    raise LLMUnavailable(
                        f"Ollama вернул нечитаемый ответ (не JSON). Первые символы: {raw[:120]!r}"
                    ) from exc
                content = (data.get("message") or {}).get("content", "")
                if not content:
                    raise LLMUnavailable("Ollama вернул пустой ответ")
                return content
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                last_error = exc
                logger.warning("Ollama недоступен (попытка %s): %s", attempt + 1, exc)
                if attempt < self.retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise LLMUnavailable(f"Ollama недоступен: {self.base_url}") from last_error

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embeddings через /api/embed с fallback на /api/embeddings.

        Используется отдельная модель для векторов (embed_model) — чат-модель
        не умеет embeddings и Ollama вернёт ошибку.
        """
        if not texts:
            return []
        client = await self._client_instance()
        try:
            response = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.embed_model, "input": texts},
            )
            if response.status_code == 200:
                data = response.json()
                return [list(map(float, vec)) for vec in data.get("embeddings", [])]
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise LLMUnavailable(f"Ollama недоступен: {exc}") from exc
        # Fallback: по одному тексту через /api/embeddings
        result: list[list[float]] = []
        for text in texts:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
            )
            if response.status_code != 200:
                raise LLMUnavailable(
                    f"Ollama вернул HTTP {response.status_code} для /api/embeddings "
                    f"(модель '{self.embed_model}'). Проверьте: ollama pull {self.embed_model}"
                )
            result.append(list(map(float, response.json().get("embedding", []))))
        return result

    async def list_models(self) -> list[str]:
        """Список установленных моделей из /api/tags (пусто, если Ollama выключена)."""
        try:
            client = await self._client_instance()
            response = await client.get(f"{self.base_url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                return [str(m.get("name", "")) for m in data.get("models", []) if m.get("name")]
        except Exception:  # noqa: BLE001 — Ollama может быть выключена
            pass
        return []

    async def auto_pick_model(self, preferred: tuple[str, ...] = ()) -> str:
        """Проверяет, что self.model реально установлена в Ollama.

        Если в .env модель не указана (или указана несуществующая) — бот сам
        выбирает рабочую модель: сначала из preferred, затем любую чат-модель.
        Возвращает выбранное имя модели (обновляет self.model при замене).
        """
        available = await self.list_models()
        if not available:
            return self.model
        if self.model in available:
            return self.model
        short = self.model.split(":")[0]
        if any(m.split(":")[0] == short for m in available):
            return self.model
        for pref in preferred:
            for name in available:
                if name.startswith(pref):
                    logger.warning(
                        "Модель %s не установлена в Ollama — переключаюсь на %s",
                        self.model,
                        name,
                    )
                    self.model = name
                    return name
        for name in available:
            if "embed" in name.lower():
                continue
            logger.warning(
                "Модель %s не установлена в Ollama — переключаюсь на %s",
                self.model,
                name,
            )
            self.model = name
            return name
        return self.model

    async def health(self) -> bool:
        """Ollama жива И нужная модель установлена."""
        try:
            available = await self.list_models()
            if not available:
                return False
            return any(
                name == self.model or name.split(":")[0] == self.model.split(":")[0]
                for name in available
            )
        except Exception:  # noqa: BLE001
            return False

    def __repr__(self) -> str:  # для логов — без токенов
        return f"OllamaLLMProvider(model={self.model}, url={self.base_url})"
