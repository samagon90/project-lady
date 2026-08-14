"""Провайдер изображений через локальный ComfyUI (бесплатный, open source).

Workflow загружается из JSON-файла проекта. Значения (промпты, seed,
размер, шаги, cfg, checkpoint, LoRA) подставляются в узлы по названию
(title узла в ComfyUI) — см. workflows/comfyui_leya_sd15.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

import httpx

from src.providers.base import ImageProviderError, ImageProviderUnavailable, ImageRequest
from src.utils import safe_filename

logger = logging.getLogger(__name__)

# Узлы, в которые подставляются значения (по title, fallback — по class_type)
_POSITIVE_TITLES = ("Positive Prompt",)
_NEGATIVE_TITLES = ("Negative Prompt",)
_CHECKPOINT_TITLES = ("Load Checkpoint",)
_LORA_TITLES = ("Load LoRA",)
_KSAmpLER_TITLES = ("KSampler",)
_LATENT_TITLES = ("Empty Latent Image",)
_SAVE_TITLES = ("Save Image",)


class ComfyUIProvider:
    def __init__(
        self,
        base_url: str,
        workflow_path: Path,
        *,
        checkpoint: str = "",
        lora: str = "",
        timeout_seconds: float = 600.0,
        poll_interval_seconds: float = 2.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.workflow_path = workflow_path
        self.checkpoint = checkpoint
        self.lora = lora
        self.timeout = timeout_seconds
        self.poll_interval = poll_interval_seconds
        self._client = client
        self._owns_client = client is None

    async def _client_instance(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ workflow

    def _load_workflow(self) -> dict:
        if not self.workflow_path.exists():
            raise ImageProviderError(f"Файл workflow не найден: {self.workflow_path.name}")
        try:
            data = json.loads(self.workflow_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ImageProviderError("Файл workflow повреждён") from exc
        if not isinstance(data, dict) or not data:
            raise ImageProviderError("Workflow пуст или имеет неверный формат")
        return data

    def _find_node(self, workflow: dict, titles: tuple[str, ...], class_types: tuple[str, ...]):
        for node in workflow.values():
            meta_title = (node.get("_meta") or {}).get("title", "")
            if meta_title in titles:
                return node
        for node in workflow.values():
            if node.get("class_type") in class_types:
                return node
        return None

    def _inject(self, workflow: dict, request: ImageRequest) -> None:
        positive = self._find_node(workflow, _POSITIVE_TITLES, ("CLIPTextEncode", "CLIPTextEncodeSDXL"))
        negative = self._find_node(workflow, _NEGATIVE_TITLES, ("CLIPTextEncode", "CLIPTextEncodeSDXL"))
        checkpoint_node = self._find_node(workflow, _CHECKPOINT_TITLES, ("CheckpointLoaderSimple", "CheckpointLoader"))
        lora_node = self._find_node(workflow, _LORA_TITLES, ("LoraLoader",))
        sampler = self._find_node(workflow, _KSAmpLER_TITLES, ("KSampler",))
        latent = self._find_node(workflow, _LATENT_TITLES, ("EmptyLatentImage",))
        save = self._find_node(workflow, _SAVE_TITLES, ("SaveImage",))

        if positive is None or negative is None or sampler is None:
            raise ImageProviderError("Workflow не содержит узлов Positive/Negative Prompt и KSampler")
        positive["inputs"]["text"] = request.prompt
        negative["inputs"]["text"] = request.negative_prompt
        sampler["inputs"]["seed"] = request.seed
        sampler["inputs"]["steps"] = request.steps
        sampler["inputs"]["cfg"] = request.cfg
        if latent is not None:
            latent["inputs"]["width"] = request.width
            latent["inputs"]["height"] = request.height
        if save is not None:
            save["inputs"]["filename_prefix"] = f"leya/{safe_filename('img', '')[:-1]}"
        if checkpoint_node is not None and self.checkpoint:
            checkpoint_node["inputs"]["ckpt_name"] = self.checkpoint
        if lora_node is not None and self.lora:
            lora_node["inputs"]["lora_name"] = self.lora

    # ------------------------------------------------------------------ generate

    async def generate(self, request: ImageRequest) -> list[bytes]:
        workflow = self._load_workflow()
        self._inject(workflow, request)
        client = await self._client_instance()
        try:
            response = await client.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow, "client_id": str(uuid.uuid4())},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise ImageProviderUnavailable("ComfyUI недоступен") from exc
        if response.status_code != 200:
            raise ImageProviderError(f"ComfyUI отклонил workflow (HTTP {response.status_code})")
        prompt_id = response.json().get("prompt_id")
        if not prompt_id:
            raise ImageProviderError("ComfyUI не вернул prompt_id")

        images = await self._wait_and_fetch(client, prompt_id)
        if not images:
            raise ImageProviderError("ComfyUI не вернул изображения")
        return images

    async def _wait_and_fetch(self, client: httpx.AsyncClient, prompt_id: str) -> list[bytes]:
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            try:
                history = await client.get(f"{self.base_url}/history/{prompt_id}")
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                raise ImageProviderUnavailable("ComfyUI недоступен") from exc
            if history.status_code == 200:
                data = history.json()
                entry = data.get(prompt_id)
                if entry and entry.get("outputs"):
                    return await self._fetch_images(client, entry["outputs"])
                status = entry.get("status", {}) if entry else {}
                if status.get("status_str") == "error":
                    raise ImageProviderError("Ошибка генерации в ComfyUI")
            if asyncio.get_running_loop().time() > deadline:
                raise ImageProviderError("Превышено время ожидания генерации")
            await asyncio.sleep(self.poll_interval)

    async def _fetch_images(self, client: httpx.AsyncClient, outputs: dict) -> list[bytes]:
        images: list[bytes] = []
        for node_output in outputs.values():
            for image in node_output.get("images", []):
                response = await client.get(
                    f"{self.base_url}/view",
                    params={
                        "filename": image.get("filename", ""),
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    },
                )
                if response.status_code == 200:
                    images.append(response.content)
        return images

    async def health(self) -> bool:
        try:
            client = await self._client_instance()
            response = await client.get(f"{self.base_url}/system_stats", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
