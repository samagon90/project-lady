"""Семантическая память: векторный индекс (numpy, опционально FAISS) + embeddings.

Главный инвариант безопасности: любой поиск фильтруется по telegram_user_id
ДО возврата результатов. Индекс может содержать векторы всех пользователей,
но наружу отдаются только факты владельца запроса.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np

from src.providers.base import EmbeddingsProvider, LLMUnavailable

logger = logging.getLogger(__name__)

try:  # FAISS — опциональная зависимость
    import faiss  # type: ignore[import-not-found]

    _FAISS_AVAILABLE = True
except ImportError:
    faiss = None  # type: ignore[assignment]
    _FAISS_AVAILABLE = False


class SemanticMemoryStore:
    """Индекс векторов памяти. Поддерживает добавление, удаление и поиск."""

    def __init__(self, dim: int, use_faiss: bool = False) -> None:
        self.dim = dim
        self._use_faiss = bool(use_faiss and _FAISS_AVAILABLE and faiss is not None)
        # item_id -> telegram_user_id (для фильтрации прав владельца)
        self._owners: dict[int, int] = {}
        self._vectors: dict[int, np.ndarray] = {}
        # порядок добавления (нужен FAISS, т.к. IndexFlatIP не умеет remove)
        self._faiss_order: list[int] = []
        if self._use_faiss:
            self._index = faiss.IndexFlatIP(dim)
        else:
            self._index = None

    @property
    def backend(self) -> str:
        return "faiss" if self._use_faiss else "numpy"

    def __len__(self) -> int:
        return len(self._vectors)

    def add(self, item_id: int, telegram_user_id: int, vector: Sequence[float]) -> None:
        vec = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        if vec.shape[1] != self.dim:
            logger.warning("Вектор размерности %s не совпадает с dim=%s", vec.shape[1], self.dim)
            return
        if item_id in self._vectors:
            self.remove(item_id)
        self._owners[item_id] = telegram_user_id
        self._vectors[item_id] = vec
        if self._index is not None:
            self._index.add(vec)
            self._faiss_order.append(item_id)

    def remove(self, item_id: int) -> None:
        if item_id not in self._vectors:
            return
        self._owners.pop(item_id, None)
        self._vectors.pop(item_id, None)
        if self._index is not None:
            # IndexFlatIP не умеет remove — пересобираем индекс
            self._rebuild_faiss()

    def search(
        self,
        vector: Sequence[float],
        k: int,
        *,
        allowed_owner_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Поиск ближайших. Возвращает только (item_id, score) владельцев из allowed."""
        query = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        if self._index is not None and self._faiss_order:
            scores, indices = self._index.search(query, k=min(k, len(self._faiss_order)))
            results: list[tuple[int, float]] = []
            for score, idx in zip(scores[0], indices[0], strict=False):
                if idx < 0 or idx >= len(self._faiss_order):
                    continue
                item_id = self._faiss_order[int(idx)]
                if allowed_owner_ids is not None and self._owners.get(item_id) not in allowed_owner_ids:
                    continue
                results.append((item_id, float(score)))
            return results[:k]
        scored: list[tuple[int, float]] = []
        for item_id, vec in self._vectors.items():
            if allowed_owner_ids is not None and self._owners.get(item_id) not in allowed_owner_ids:
                continue
            score = float(np.dot(vec.reshape(-1), query.reshape(-1)))
            scored.append((item_id, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def _rebuild_faiss(self) -> None:
        if self._index is None or faiss is None:
            return
        new_index = faiss.IndexFlatIP(self.dim)
        ids_in_order: list[int] = []
        for item_id in self._faiss_order:
            vec = self._vectors.get(item_id)
            if vec is None:
                continue
            new_index.add(vec)
            ids_in_order.append(item_id)
        self._index = new_index
        self._faiss_order = ids_in_order


class EmbeddingsService:
    """Обёртка: провайдер embeddings + индекс + персистентность в БД."""

    def __init__(
        self,
        provider: EmbeddingsProvider,
        store: SemanticMemoryStore,
        *,
        model: str,
    ) -> None:
        self.provider = provider
        self.store = store
        self.model = model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return await self.provider.embed(texts)

    async def embed_one(self, text: str) -> list[float] | None:
        try:
            vectors = await self.provider.embed([text])
            return vectors[0] if vectors else None
        except LLMUnavailable:
            logger.warning("Embeddings недоступны — семантический поиск отключён")
            return None

    def pack(self, vector: list[float]) -> bytes:
        return np.asarray(vector, dtype=np.float32).tobytes()

    def unpack(self, blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)

    def load_all(self, rows: list[tuple[int, int, bytes]]) -> None:
        """Прогрев индекса из БД при старте."""
        for item_id, owner_id, blob in rows:
            vec = self.unpack(blob)
            self.store.add(item_id, owner_id, vec.tolist())
        logger.info(
            "Семантический индекс прогрет: %s фактов, backend=%s",
            len(self.store),
            self.store.backend,
        )
