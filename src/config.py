"""Конфигурация приложения через Pydantic Settings.

Все внешние интеграции (Ollama, ComfyUI, Piper, БД) настраиваются
переменными окружения / файлом .env — без изменения кода.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]

APP_VERSION = "1.7.2"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    telegram_token: str = ""

    # --- База данных ---
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"

    # --- LLM ---
    # Провайдер: ollama (локально) | openrouter | venice
    llm_provider: str = "openrouter"
    # Ollama (если llm_provider=ollama):
    llm_base_url: str = "http://127.0.0.1:11434"
    # OpenRouter: ключ и модель (NSFW-дружественные — см. README).
    # Примеры: openrouter/free (авто), deepinfra/..., novita/..., together/...
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    # Ограничить провайдеров (через запятую): DeepInfra,Novita,Together
    openrouter_providers: str = ""
    # Venice (самый либеральный NSFW): ключ и модель
    venice_api_key: str = ""
    venice_model: str = "venice/llama-3.3-70b"
    # Общие параметры LLM
    llm_model: str = "qwen2.5:7b"  # используется только для ollama
    llm_temperature: float = 1.0
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 120.0
    llm_retries: int = 2

    # --- Embeddings ---
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # --- Память ---
    memory_top_k: int = 6
    memory_min_confidence: float = 0.55
    memory_extract_every_n_messages: int = 5
    memory_store_sensitivity: str = "low,medium,high"
    memory_summarize_every_n_messages: int = 40
    memory_summarize_max_history: int = 200
    recent_messages_for_context: int = 20

    # --- Изображения (ComfyUI) ---
    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_path: Path = Path("workflows/comfyui_lilith_sd15.json")
    # Референс-изображение (аватар Лилит) для IPAdapter — «твёрдый» образ
    comfyui_reference_image: Path | None = Path("assets/emotions/lilith_playful.png")
    comfyui_checkpoint: str = "dreamshaper_8.safetensors"
    comfyui_lora: str = ""
    # Отдельные checkpoint/LoRA для NSFW-запросов (18+, вымышленный персонаж).
    # Если заданы — при эротическом запросе бот автоматически использует их.
    comfyui_nsfw_checkpoint: str = ""
    # Экстремальные NSFW-теги (hardcore, detailed genitals) — по умолчанию
    # выключены; включите, если модель-художник поддерживает и вам это нужно.
    comfyui_nsfw_extreme: bool = True
    comfyui_nsfw_lora: str = ""
    comfyui_timeout_seconds: float = 600.0
    comfyui_poll_interval_seconds: float = 2.0
    image_max_workers: int = 1
    image_photo_rate_limit_minutes: int = 0
    image_steps: int = 32
    image_cfg: float = 7.0
    image_default_size: str = "576x864"

    # --- Голос (Piper) ---
    tts_enabled: bool = True
    piper_binary: str = "piper"
    piper_voice_model: Path = Path("models/piper/ru_RU-irina-medium.onnx")
    piper_voice_config: Path | None = None
    piper_length_scale: float = 1.0
    piper_sample_rate: int = 22050
    tts_max_chars: int = 400
    voice_default_enabled: bool = False

    # --- Лимиты ---
    rate_limit_messages_per_minute: int = 30
    max_message_length: int = 4000
    max_photo_prompt_length: int = 500
    max_name_length: int = 60
    max_boundaries_length: int = 1000

    # --- Хранение ---
    data_dir: Path = Path("data")
    temp_dir: Path = Path("data/tmp")
    media_ttl_hours: int = 24
    message_retention_days: int = 30
    memory_retention_days: int = 180
    retention_interval_minutes: int = 60

    # --- Логирование и аудит ---
    log_level: str = "INFO"
    log_file: Path | None = Path("data/bot.log")
    audit_enabled: bool = True

    # Лилит прикрепляет к каждому ответу аватар с эмоцией (true/false)
    chat_avatar_enabled: bool = True

    # --- Проактивные сообщения (Лилит пишет первой) ---
    proactive_enabled: bool = True
    proactive_interval_minutes: int = 30
    proactive_min_inactivity_hours: int = 6
    proactive_max_per_day: int = 3

    # --- Telegram Mini App ---
    miniapp_host: str = "0.0.0.0"
    miniapp_port: int = 8001
    # Публичный HTTPS-адрес мини-приложения (например, туннель localtunnel).
    # Если пусто — кнопка /app не показывается.
    webapp_url: str = ""

    # --- Запуск ---
    polling_timeout_seconds: int = 60

    @field_validator("llm_base_url", "comfyui_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("memory_store_sensitivity")
    @classmethod
    def _validate_sensitivity(cls, value: str) -> str:
        allowed = {"low", "medium", "high"}
        parts = {p.strip() for p in value.split(",") if p.strip()}
        unknown = parts - allowed
        if unknown:
            raise ValueError(f"Недопустимые уровни чувствительности: {sorted(unknown)}")
        return ",".join(sorted(parts))

    @field_validator("image_default_size")
    @classmethod
    def _validate_image_size(cls, value: str) -> str:
        try:
            w, h = (int(x) for x in value.lower().split("x"))
        except ValueError as exc:
            raise ValueError("IMAGE_DEFAULT_SIZE должен быть вида WIDTHxHEIGHT, например 512x768") from exc
        if w < 256 or h < 256 or w > 1536 or h > 1536 or w % 8 or h % 8:
            raise ValueError("IMAGE_DEFAULT_SIZE: размеры от 256 до 1536, кратны 8")
        return f"{w}x{h}"

    @property
    def default_image_size(self) -> tuple[int, int]:
        w, h = self.image_default_size.lower().split("x")
        return int(w), int(h)

    @property
    def llm_api_url(self) -> str:
        return f"{self.llm_base_url}/api"

    @property
    def comfyui_api_url(self) -> str:
        return f"{self.comfyui_base_url}"

    def resolve_path(self, path: Path) -> Path:
        """Пути из конфига могут быть относительными — резолвим от корня проекта."""
        if path.is_absolute():
            return path
        return (PROJECT_ROOT / path).resolve()

    @property
    def resolved_temp_dir(self) -> Path:
        return self.resolve_path(self.temp_dir)

    @property
    def resolved_data_dir(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def resolved_workflow_path(self) -> Path:
        return self.resolve_path(self.comfyui_workflow_path)

    @property
    def resolved_piper_voice_model(self) -> Path:
        return self.resolve_path(self.piper_voice_model)

    @property
    def resolved_piper_voice_config(self) -> Path | None:
        if not self.piper_voice_config:
            return None
        return self.resolve_path(self.piper_voice_config)

    @property
    def piper_auto_config(self) -> Path:
        """Файл .onnx.json рядом с голосовой моделью, если конфиг не задан явно."""
        return self.resolved_piper_voice_model.with_suffix(".onnx.json")

    def require_token(self) -> None:
        if not self.telegram_token:
            raise RuntimeError("TELEGRAM_TOKEN не задан. Скопируйте .env.example в .env и укажите токен от @BotFather.")


def settings_from_env() -> Settings:
    return Settings()
