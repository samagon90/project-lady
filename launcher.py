"""Запуск и автоустановка бота «Лея» на Windows — без знания программирования.

Что делает start_windows.bat:
- если Python не установлен — ставит его сам (winget);
- запускает этот файл:
  * start  — установка зависимостей, настройка .env (Блокнот сам открывается),
             проверка компонентов и запуск бота;
  * setup  — автоустановка всего: Ollama + модель, ffmpeg, Piper + русский
             голос, опционально ComfyUI; затем запуск.

Все сообщения на русском печатает Python — поэтому в любом Windows
они отображаются корректно (в отличие от текста внутри .bat-файла).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PI = "piper"  # папка для бинарника Piper рядом с проектом


def run(args) -> None:
    """Запуск команды с выводом в то же окно (виден прогресс)."""
    print(f"\n>> {' '.join(str(a) for a in args)}\n")
    subprocess.run([str(a) for a in args], cwd=str(ROOT), check=False)


def ask(question: str, options: dict[str, str]) -> str:
    """Простое меню: вопрос, варианты, возвращает выбранный ключ."""
    print()
    print(question)
    for key, label in options.items():
        print(f"  [{key}] {label}")
    while True:
        choice = input("Ваш выбор: ").strip().lower()
        if choice in options:
            return choice
        print("Пожалуйста, введите один из вариантов:", ", ".join(options))


def ram_gb() -> float:
    """Объём оперативной памяти (Windows)."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        return stat.ullTotalPhys / (1024**3)
    except Exception:
        return 0.0


def winget(app_id: str) -> bool:
    """Установка приложения через winget (если доступен)."""
    if shutil.which("winget") is None:
        return False
    run(["winget", "install", "-e", "--id", app_id, "--silent",
         "--accept-package-agreements", "--accept-source-agreements"])
    return True


# ================================================================== компоненты

def ensure_ollama() -> bool:
    if shutil.which("ollama"):
        print("✅ Ollama уже установлена.")
        return True
    print("Устанавливаю Ollama... (это займёт пару минут)")
    winget("Ollama.Ollama")
    # после установки PATH в текущем окне не обновился — ищем по стандартному пути
    for candidate in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Ollama" / "ollama.exe",
    ):
        if candidate.exists():
            os.environ["PATH"] = str(candidate.parent) + os.pathsep + os.environ.get("PATH", "")
            break
    if shutil.which("ollama"):
        print("✅ Ollama установлена.")
        return True
    print("❌ Не удалось установить Ollama автоматически.")
    print("   Скачайте её сами: https://ollama.com/download  (кнопка Download for Windows)")
    print("   Установите как обычную программу и запустите start_windows.bat снова.")
    return False


def pull_models() -> None:
    """Выбор и скачивание языковой модели + модели для памяти."""
    gb = ram_gb()
    print(f"\nОбнаружено памяти: {gb:.0f} ГБ")
    if gb and gb < 8:
        print("Для 8 ГБ и меньше рекомендую маленькую модель (qwen2.5:3b).")
    else:
        print("Рекомендую модель без цензуры для свободного NSFW (7b).")
    choice = ask(
        "Какую модель скачать? (от этого зависит «раскованность» Леи)",
        {
            "abl": "Развратная без цензуры (huihui_ai/qwen2.5-abliterated:7b, ~5 ГБ) — рекомендую",
            "3b": "Компактная (qwen2.5:3b, ~2 ГБ) — для слабых ПК",
            "7b": "Стандартная (qwen2.5:7b, ~5 ГБ) — цензура встроена, NSFW хуже",
        },
    )
    if choice == "abl":
        model = "huihui_ai/qwen2.5-abliterated:7b"
    elif choice == "3b":
        model = "qwen2.5:3b"
    else:
        model = "qwen2.5:7b"
    print(f"\nСкачиваю модель {model}... это 2-30 минут, не выключайте компьютер.")
    run(["ollama", "pull", model])
    print("Скачиваю маленькую модель для памяти (nomic-embed-text)...")
    run(["ollama", "pull", "nomic-embed-text"])
    # прописываем модель в .env
    env = ROOT / ".env"
    if env.exists():
        text = env.read_text(encoding="utf-8")
        lines = [line if not line.startswith("LLM_MODEL=") else f"LLM_MODEL={model}" for line in text.splitlines()]
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"✅ В .env записано: LLM_MODEL={model}")


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        print("✅ ffmpeg уже установлен.")
        return
    print("Устанавливаю ffmpeg (нужен для голосовых)...")
    if winget("Gyan.FFmpeg"):
        if shutil.which("ffmpeg"):
            print("✅ ffmpeg установлен.")
            return
    print("⚠️ ffmpeg не установился автоматически. Голос будет работать после")
    print("   ручной установки: https://www.gyan.dev/ffmpeg/builds/ (release essentials zip,")
    print("   распаковать, папку bin добавить в PATH). Бот без голоса запустится.")


def ensure_piper() -> None:
    if shutil.which("piper") or (ROOT / PI / "piper.exe").exists():
        print("✅ Piper уже установлен.")
        return
    arch = os.environ.get("PROCESSOR_ARCHITECTURE", "").lower()
    pkg = "piper_arm64.tar.gz" if "arm" in arch else "piper_amd64.tar.gz"
    url = f"https://github.com/rhasspy/piper/releases/download/1.2.0/{pkg}"
    print(f"Скачиваю Piper ({pkg}, ~40 МБ)...")
    try:
        archive = ROOT / pkg
        urllib.request.urlretrieve(url, archive)  # noqa: S310
        import tarfile

        with tarfile.open(archive) as tf:
            tf.extractall(ROOT / PI)
        archive.unlink(missing_ok=True)
        exe = ROOT / PI / "piper.exe"
        if exe.exists():
            print("✅ Piper установлен.")
            os.environ["PATH"] = str(ROOT / PI) + os.pathsep + os.environ.get("PATH", "")
        else:
            print("❌ Не удалось распаковать Piper — установите вручную:")
            print("   https://github.com/rhasspy/piper/releases")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Ошибка скачивания Piper: {exc}")
        print("   Установите вручную: https://github.com/rhasspy/piper/releases")


def ensure_voice() -> None:
    voice_dir = ROOT / "models" / "piper"
    onnx = voice_dir / "ru_RU-irina-medium.onnx"
    if onnx.exists():
        print("✅ Русский голос уже скачан.")
        return
    voice_dir.mkdir(parents=True, exist_ok=True)
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium"
    for name in ("ru_RU-irina-medium.onnx", "ru_RU-irina-medium.onnx.json"):
        print(f"Скачиваю голос ({name}, ~100 МБ суммарно)...")
        try:
            urllib.request.urlretrieve(f"{base}/{name}", voice_dir / name)  # noqa: S310
        except Exception as exc:  # noqa: BLE001
            print(f"❌ Не удалось скачать голос: {exc}")
            print("   Повторите позже командой:  make voice")
            return
    print("✅ Русский голос установлен.")


def ensure_comfyui() -> None:
    """Опциональная установка ComfyUI (для картинок /photo). Долго (~15-30 мин)."""
    comfy_dir = ROOT.parent / "ComfyUI"
    print()
    print("Установка ComfyUI — это долго (15-30 минут) и требует ~10 ГБ места.")
    print("Картинки на обычном ПК без видеокарты генерируются 2-10 минут каждая.")
    if ask("Ставим ComfyUI?", {"y": "Да, ставь", "n": "Нет, пропустить"}) != "y":
        return
    if not comfy_dir.exists():
        print("Клонирую ComfyUI...")
        run(["git", "clone", "https://github.com/comfyanonymous/ComfyUI.git", str(comfy_dir)])
    python = sys.executable
    run([python, "-m", "venv", str(comfy_dir / "venv")])
    comfy_py = comfy_dir / "venv" / "Scripts" / "python.exe"
    print("Ставлю torch (CPU-версия, ~2.5 ГБ)...")
    run([comfy_py, "-m", "pip", "install", "torch", "torchvision",
         "--index-url", "https://download.pytorch.org/whl/cpu"])
    run([comfy_py, "-m", "pip", "install", "-r", str(comfy_dir / "requirements.txt")])
    print()
    print("✅ ComfyUI установлен.")
    print("Осталось скачать модель-«художника» (checkpoint, ~2-7 ГБ):")
    print("  https://civitai.com — ищите по тегу «explicit» (например, majicMIX realistic)")
    print("  Файл .safetensors положите в: ComfyUI/models/checkpoints/")
    print("  Затем в .env пропишите: COMFYUI_NSFW_CHECKPOINT=имя_файла.safetensors")
    print()
    print("Запускать ComfyUI так (каждый раз, когда нужны картинки):")
    print(f'  {comfy_py} "{comfy_dir / "main.py"}" --listen 127.0.0.1 --port 8188')
    print("Или скопируйте файл start_comfyui.bat из папки бота в папку ComfyUI.")


# ================================================================== установка всего

def setup() -> None:
    print("=" * 60)
    print("  АВТОУСТАНОВКА всего для бота «Лея»")
    print("  На каждый вопрос отвечайте цифрой и жмите Enter.")
    print("=" * 60)
    ensure_ollama()
    if shutil.which("ollama"):
        pull_models()
    ensure_ffmpeg()
    ensure_piper()
    ensure_voice()
    ensure_comfyui()
    print()
    print("=" * 60)
    print("  Установка завершена!")
    print("  Дальше: впишите токен (Блокнот откроется сам) и бот запустится.")
    print("=" * 60)
    input("Нажмите Enter, чтобы продолжить...")


# ================================================================== запуск

def venv_ready() -> bool:
    return VENV_PY.exists()


def create_venv() -> None:
    print("Готовлю окружение... (первый запуск, 2-5 минут)")
    run([sys.executable, "-m", "venv", str(ROOT / ".venv")])


def install_deps() -> None:
    print("Устанавливаю программы бота... (1-3 минуты)")
    run([VENV_PY, "-m", "pip", "install", "-q", "-e", "."])


def token_from_env() -> str:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return ""
    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if line.startswith("TELEGRAM_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def ask_token_in_notepad() -> None:
    env = ROOT / ".env"
    print()
    print("=" * 60)
    print("Нужно один раз вписать токен вашего бота.")
    print("=" * 60)
    print()
    print("1) Сейчас откроется Блокнот с файлом настроек .env.")
    print("2) Найдите строку:  TELEGRAM_TOKEN=")
    print("3) Впишите сразу после знака = ваш токен от @BotFather")
    print("   (длинная строка из букв и цифр, которую вы скопировали у BotFather)")
    print("   БЕЗ пробелов. Пример:")
    print("   TELEGRAM_TOKEN=7123456789:AAHfK3x8yQWERTY...")
    print("4) Нажмите Ctrl+S (сохранить) и закройте Блокнот.")
    print()
    print("Открываю Блокнот...")
    subprocess.run(["notepad", str(env)], check=False)
    if not token_from_env():
        print()
        print("Токен пока не найден. Возможно, вы не сохранили файл.")
        print("Открываю Блокнот ещё раз — попробуйте ещё раз и нажмите Ctrl+S.")
        subprocess.run(["notepad", str(env)], check=False)


def ensure_env() -> bool:
    env = ROOT / ".env"
    if not env.exists():
        example = ROOT / ".env.example"
        if example.exists():
            env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print("Создан файл настроек .env.")
    if not token_from_env():
        ask_token_in_notepad()
    if token_from_env():
        print("Токен найден. Отлично!")
        return True
    print()
    print("Токен так и не найден. Бот не сможет запуститься без него.")
    print("Запустите start_windows.bat снова и повторите шаг с Блокнотом.")
    return False


def check_components() -> None:
    """Проверка внешних программ; предлагает автоустановку недостающего."""
    missing = []
    if shutil.which("ollama") is None:
        missing.append("Ollama (мозг бота)")
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg (для голоса)")
    if shutil.which("piper") is None and not (ROOT / PI / "piper.exe").exists():
        missing.append("Piper (голос)")
    if not missing:
        print("✅ Все внешние программы на месте.")
        return
    print()
    print("Не установлены: " + ", ".join(missing))
    choice = ask(
        "Хотите, чтобы я установил(а) их автоматически?",
        {"y": "Да, установи всё сам(а)", "n": "Нет, пропустить (бот запустится без голоса)"},
    )
    if choice == "y":
        setup()


def migrate() -> None:
    print("Настраиваю базу данных...")
    run([VENV_PY, "-m", "alembic", "upgrade", "head"])


def run_bot() -> None:
    print()
    print("Бот работает! НЕ ЗАКРЫВАЙТЕ это окно.")
    print("Чтобы остановить бота — закройте это окно (или нажмите Ctrl+C).")
    print()
    run([VENV_PY, "-m", "src.main"])
    print("Бот остановлен.")


# ================================================================== main

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "start"
    if mode == "setup":
        setup()
        return
    if not venv_ready():
        create_venv()
    install_deps()
    if mode == "check":
        run([VENV_PY, "scripts", "doctor.py"])
        return
    if not ensure_env():
        input("Нажмите Enter, чтобы закрыть окно...")
        sys.exit(1)
    check_components()
    migrate()
    run_bot()


if __name__ == "__main__":
    main()
