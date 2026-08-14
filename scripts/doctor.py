"""Диагностика окружения перед запуском: показывает, что готово, а чего не хватает.

Запуск: make doctor  (или .venv/bin/python scripts/doctor.py)

✅ — всё готово;  ⚠️ — бот запустится, но функция недоступна;  ❌ — нужно исправить.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Settings  # noqa: E402

FAILED = False


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def fail(msg: str) -> None:
    global FAILED
    FAILED = True
    print(f"  ❌ {msg}")


# ================================================================== sync-проверки

def check_python() -> None:
    print("1. Python")
    # Проверка намеренная: doctor диагностирует и старые Python, поэтому
    # не может полагаться на target-version проекта (py312).
    if sys.version_info >= (3, 12):  # noqa: UP036
        ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} (нужен 3.12+)")
    else:
        fail(
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} — "
            "нужен 3.12+ (Ubuntu 24.04, deadsnakes или uv)"
        )


def check_env(settings: Settings) -> None:
    print("2. Конфигурация (.env)")
    env_path = ROOT / ".env"
    if env_path.exists():
        ok(".env найден")
    else:
        fail(".env не найден — выполните: cp .env.example .env")
    if settings.telegram_token:
        ok("TELEGRAM_TOKEN задан")
    else:
        fail("TELEGRAM_TOKEN пуст — вставьте токен от @BotFather")


def check_db_and_migrations(settings: Settings) -> None:
    print("3. База данных и миграции")
    try:
        from alembic import command
        from alembic.config import Config

        config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(config, "head")
        ok(f"Миграции применены ({settings.database_url})")
    except Exception as exc:  # noqa: BLE001
        fail(f"Миграции не применились: {exc}")
    try:
        from src.database.base import Database

        async def _ping() -> None:
            db = Database(settings.database_url)
            await db.connect()
            await db.close()

        asyncio.run(_ping())
        ok("Подключение к БД работает")
    except Exception as exc:  # noqa: BLE001
        fail(f"БД недоступна: {exc}")


# ================================================================== async-проверки

async def check_ollama(settings: Settings) -> None:
    print("4. LLM и embeddings (Ollama)")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{settings.llm_base_url}/api/tags")
            if response.status_code != 200:
                fail(f"Ollama ответил HTTP {response.status_code}")
                return
            models = [m.get("name", "") for m in response.json().get("models", [])]
            ok(f"Ollama доступен ({settings.llm_base_url}), моделей: {len(models)}")
            if settings.llm_model in models:
                ok(f"LLM-модель {settings.llm_model} установлена")
            else:
                fail(f"Модель {settings.llm_model} не найдена — выполните: ollama pull {settings.llm_model}")
            if settings.embedding_model in models:
                ok(f"Embedding-модель {settings.embedding_model} установлена")
            else:
                fail(
                    f"Модель {settings.embedding_model} не найдена — выполните: "
                    f"ollama pull {settings.embedding_model}"
                )
    except Exception:  # noqa: BLE001
        fail(
            f"Ollama недоступен ({settings.llm_base_url}). Установка: "
            "curl -fsSL https://ollama.com/install.sh | sh, затем: ollama serve"
        )


async def check_piper(settings: Settings) -> None:
    print("5. Голос (Piper + ffmpeg)")
    binary = shutil.which(settings.piper_binary)
    if binary:
        ok(f"piper найден: {binary}")
    else:
        fail(
            "piper не найден в PATH. Скачайте с "
            "https://github.com/rhasspy/piper/releases (piper_amd64.tar.gz / "
            "piper_arm64.tar.gz) и добавьте в PATH, или установите через pipx: "
            "pipx install piper-tts"
        )
    voice = settings.resolved_piper_voice_model
    if voice.exists():
        ok(f"Голосовой модель: {voice}")
    else:
        fail(f"Голос не найден ({voice}) — выполните: make voice")
    if shutil.which("ffmpeg"):
        ok("ffmpeg найден")
    else:
        fail("ffmpeg не найден — установите: sudo apt install ffmpeg (Linux) / winget install ffmpeg (Windows)")


async def check_comfyui(settings: Settings) -> None:
    print("6. Изображения (ComfyUI)")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{settings.comfyui_base_url}/system_stats")
            if response.status_code != 200:
                fail(f"ComfyUI ответил HTTP {response.status_code}")
                return
            ok(f"ComfyUI доступен ({settings.comfyui_base_url})")
        workflow = settings.resolved_workflow_path
        if workflow.exists():
            ok(f"Workflow: {workflow.name}")
        else:
            fail(f"Workflow не найден: {workflow}")
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                info = await client.get(
                    f"{settings.comfyui_base_url}/object_info/CheckpointLoaderSimple"
                )
                required = info.json().get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {})
                options = required.get("ckpt_name", [])
                names = [opt[0] if isinstance(opt, list) else opt for opt in options]
            if settings.comfyui_checkpoint in names:
                ok(f"Checkpoint {settings.comfyui_checkpoint} найден")
            else:
                available = ", ".join(names[:10]) or "—"
                fail(
                    f"Checkpoint {settings.comfyui_checkpoint} не найден. Доступны: {available}. "
                    "Положите файл .safetensors в ComfyUI/models/checkpoints/ и перезапустите ComfyUI"
                )
        except Exception:  # noqa: BLE001
            warn("Не удалось проверить checkpoint (endpoint object_info недоступен)")
    except Exception:  # noqa: BLE001
        warn(
            f"ComfyUI недоступен ({settings.comfyui_base_url}) — бот запустится, "
            "но команда /photo будет сообщать об ошибке. Установка: см. README, раздел ComfyUI"
        )


async def check_storage(settings: Settings) -> None:
    print("7. Каталоги данных")
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_temp_dir.mkdir(parents=True, exist_ok=True)
    ok(f"Данные: {settings.resolved_data_dir}")
    ok(f"Временные файлы: {settings.resolved_temp_dir}")


async def async_checks(settings: Settings) -> None:
    await check_ollama(settings)
    await check_piper(settings)
    await check_comfyui(settings)
    await check_storage(settings)


def main() -> None:
    settings = Settings()
    check_python()
    check_env(settings)
    check_db_and_migrations(settings)
    asyncio.run(async_checks(settings))
    print()
    if FAILED:
        print("Есть ❌ — исправьте указанные пункты и запустите make doctor снова.")
        print("Если все ✅ — запускайте: make run")
    else:
        print("Всё готово! Запускайте: make run")


if __name__ == "__main__":
    main()
