"""Запуск и автоустановка бота «Лилит» на Windows — без знания программирования.

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

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
VERSION = "0.9.3"

# Минимальный размер настоящего checkpoint (меньше — точно HTML/мусор)
MIN_CHECKPOINT_BYTES = 50 * 1024 * 1024

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PI = "piper"  # папка для бинарника Piper рядом с проектом


def run(args) -> int:
    """Запуск команды с выводом в то же окно; возвращает код возврата.

    Если команда не найдена (например, нет git) — печатает понятное
    сообщение и возвращает ненулевой код вместо падения с Traceback.
    """
    print(f"\n>> {' '.join(str(a) for a in args)}\n")
    try:
        return subprocess.run([str(a) for a in args], cwd=str(ROOT), check=False).returncode
    except FileNotFoundError:
        print(f"⚠️ Программа не найдена: {args[0]}. Продолжаю без неё.")
        return 1
    except OSError as exc:
        print(f"⚠️ Не удалось запустить {args[0]}: {exc}")
        return 1


def download(url: str, dest: Path) -> bool:
    """Скачивание файла: сначала curl.exe (системные сертификаты Windows),
    затем venv-питон с certifi. Возвращает True при успехе."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("curl"):
        code = run(["curl", "-L", "--fail", "--connect-timeout", "30", "-o", str(dest), url])
        if code == 0 and dest.exists() and dest.stat().st_size > 0:
            return True
        print("curl не справился — пробую другой способ...")
    if VENV_PY.exists():
        code = run([VENV_PY, str(ROOT / "scripts" / "download.py"), url, str(dest)])
        if code == 0 and dest.exists() and dest.stat().st_size > 0:
            return True
    print(f"❌ Не удалось скачать: {url}")
    return False


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
            "abl": "Без цензуры (dolphin-llama3:8b, ~4.7 ГБ) — надёжная, рекомендую",
            "qabl": "Без цензуры Qwen (huihui_ai/qwen2.5-abliterate:7b, ~5 ГБ) — ВНИМАНИЕ: может отвечать иероглифами",
            "3b": "Компактная (qwen2.5:3b, ~2 ГБ) — для слабых ПК",
            "7b": "Стандартная (qwen2.5:7b, ~5 ГБ) — цензура встроена, но надёжная",
        },
    )
    candidates = {
        "abl": [
            "dolphin-llama3:8b",
            "qwen2.5:7b",             # запас: надёжная, цензура
        ],
        "qabl": [
            "huihui_ai/qwen2.5-abliterate:7b",
            "dolphin-llama3:8b",      # запас
            "qwen2.5:7b",             # крайний запас
        ],
        "3b": ["qwen2.5:3b"],
        "7b": ["qwen2.5:7b"],
    }[choice]
    chosen = None
    for model in candidates:
        print(f"\nСкачиваю модель {model}... это 2-30 минут, не выключайте компьютер.")
        if run(["ollama", "pull", model]) != 0:
            print(f"⚠️ Не удалось скачать {model}. Пробую следующую...")
            continue
        # Проверяем, что модель реально отвечает по-русски (не иероглифами)
        if llm_speaks_russian(model):
            chosen = model
            break
        print(f"⚠️ Модель {model} скачалась, но отвечает не по-русски. Пробую следующую...")
    if chosen is None:
        print("❌ Ни одна модель не скачалась. Проверьте интернет и повторите позже.")
        return
    print("Скачиваю маленькую модель для памяти (nomic-embed-text)...")
    run(["ollama", "pull", "nomic-embed-text"])
    # прописываем успешно скачанную модель в .env
    env = ROOT / ".env"
    if env.exists():
        text = env.read_text(encoding="utf-8")
        lines = [line if not line.startswith("LLM_MODEL=") else f"LLM_MODEL={chosen}" for line in text.splitlines()]
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"✅ В .env записано: LLM_MODEL={chosen}")


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        print("✅ ffmpeg уже установлен.")
        return
    print("Устанавливаю ffmpeg (нужен для голосовых)...")
    if winget("Gyan.FFmpeg") and shutil.which("ffmpeg"):
        print("✅ ffmpeg установлен.")
        return
    # Запасной способ: прямая загрузка сборки с GitHub (BtbN) рядом с ботом
    print("winget не помог — скачиваю ffmpeg напрямую (~80 МБ)...")
    zip_path = ROOT / "ffmpeg.zip"
    ffmpeg_url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    if download(ffmpeg_url, zip_path):
        import zipfile

        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(ROOT / "ffmpeg")
            zip_path.unlink(missing_ok=True)
            exe = next((p for p in (ROOT / "ffmpeg").rglob("bin/ffmpeg.exe")), None)
            if exe is not None:
                # кладём ffmpeg.exe рядом с piper — эта папка уже в PATH для бота
                (ROOT / PI).mkdir(parents=True, exist_ok=True)
                shutil.copy2(exe, ROOT / PI / "ffmpeg.exe")
                print("✅ ffmpeg установлен.")
                return
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Не удалось распаковать ffmpeg: {exc}")
    print("⚠️ ffmpeg не установился автоматически. Бот запустится, голосовые")
    print("   появятся после ручной установки (см. RUNBOOK.md, раздел 6).")


def ensure_piper() -> None:
    if shutil.which("piper") or (ROOT / PI / "piper.exe").exists():
        print("✅ Piper уже установлен.")
        return
    arch = os.environ.get("PROCESSOR_ARCHITECTURE", "").lower()
    pkg = "piper_arm64.tar.gz" if "arm" in arch else "piper_amd64.tar.gz"
    url = f"https://github.com/rhasspy/piper/releases/download/v1.2.0/{pkg}"
    print(f"Скачиваю Piper ({pkg}, ~40 МБ)...")
    archive = ROOT / pkg
    if not download(url, archive):
        print("   Установите вручную: https://github.com/rhasspy/piper/releases")
        return
    try:
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
        print(f"❌ Ошибка распаковки Piper: {exc}")
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
        if not download(f"{base}/{name}", voice_dir / name):
            print("   Повторите позже командой:  make voice")
            return
    print("✅ Русский голос установлен.")


def is_valid_checkpoint(path: Path) -> bool:
    """Проверяет, что файл — настоящий checkpoint для Stable Diffusion.

    civitai.com часто отдаёт вместо модели HTML-страницу (Cloudflare) или
    другой файл; ComfyUI тогда пишет «Could not detect model type».
    Проверяем: размер больше 50 МБ и заголовок safetensors содержит ключи
    диффузионной модели (model.diffusion_model) и текстовой части/VAE.
    """
    try:
        if path.stat().st_size < MIN_CHECKPOINT_BYTES:
            return False
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                return False
            n = struct.unpack("<Q", head)[0]
            if n <= 0 or n > 512 * 1024 * 1024:
                return False
            header = f.read(n)
            data = json.loads(header)
        keys = " ".join(data.keys())
        has_diff = "model.diffusion_model" in keys
        has_cond = "cond_stage_model" in keys or "text_model" in keys
        has_vae = "first_stage_model" in keys
        return has_diff and (has_cond or has_vae)
    except Exception:  # noqa: BLE001
        return False


def ensure_comfyui() -> None:
    """Опциональная установка ComfyUI (для картинок /photo). Долго (~15-30 мин)."""
    comfy_dir = ROOT.parent / "ComfyUI"
    print()
    print("Установка ComfyUI — это долго (15-30 минут) и требует ~10 ГБ места.")
    print("Картинки на обычном ПК без видеокарты генерируются 2-10 минут каждая.")
    if ask("Ставим ComfyUI?", {"y": "Да, ставь", "n": "Нет, пропустить"}) != "y":
        return
    if not comfy_dir.exists():
        # git может быть не установлен — поэтому качаем архив с GitHub
        print("Скачиваю ComfyUI (архив, ~12 МБ)...")
        zip_path = ROOT / "comfyui.zip"
        comfyui_url = "https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip"
        if not download(comfyui_url, zip_path):
            print("❌ Не удалось скачать ComfyUI. Картинки можно будет доустановить позже.")
            return
        try:
            import zipfile

            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(ROOT.parent)
            zip_path.unlink(missing_ok=True)
            extracted = ROOT.parent / "ComfyUI-master"
            if extracted.exists() and not comfy_dir.exists():
                extracted.rename(comfy_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ Не удалось распаковать ComfyUI: {exc}")
            return
    if not comfy_dir.exists():
        print("❌ Папка ComfyUI не появилась. Установите вручную (см. RUNBOOK.md, раздел 7).")
        return
    python = sys.executable
    run([python, "-m", "venv", str(comfy_dir / "venv")])
    comfy_py = comfy_dir / "venv" / "Scripts" / "python.exe"
    print("Ставлю torch (CPU-версия, ~2.5 ГБ)...")
    run([comfy_py, "-m", "pip", "install", "torch", "torchvision",
         "--index-url", "https://download.pytorch.org/whl/cpu"])
    run([comfy_py, "-m", "pip", "install", "-r", str(comfy_dir / "requirements.txt")])
    print()
    print("✅ ComfyUI установлен.")
    # Сразу скачиваем модель-«художника» — чтобы картинки заработали без ручных шагов
    checkpoints = comfy_dir / "models" / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    target = checkpoints / "UnstableDiffusion_ema_pruned.safetensors"
    # Если файл есть, но это НЕ настоящая модель (civitai отдал HTML-страницу) —
    # удаляем и качаем заново
    if target.exists() and not is_valid_checkpoint(target):
        print(f"⚠️ Файл {target.name} есть, но это НЕ модель (битая загрузка).")
        print("   Удаляю и скачиваю заново из другого источника...")
        try:
            target.unlink()
        except OSError:
            pass
    if target.exists():
        print(f"✅ Модель уже есть: {target.name}")
    else:
        print()
        print("Скачиваю модель-«художника» majicMIX realistic (~2 ГБ, NSFW 18+)...")
        print("Это 5-30 минут. Не закрывайте окно.")
        # Несколько источников: civitai может отдавать страницу вместо файла,
        # поэтому пробуем по очереди, пока не скачается настоящая модель.
        # API-ключ civitai из .env (CIVITAI_API_TOKEN) — скачивание надёжнее
        civitai_token = ""
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("CIVITAI_API_TOKEN="):
                    civitai_token = line.split("=", 1)[1].strip()
        sources = []
        if civitai_token:
            sources.append(
                ("civitai.com (Unstable Diffusion NSFW, с вашим API-ключом)",
                 f"https://civitai.com/api/download/models/91623?token={civitai_token}")
            )
        sources += [
            ("civitai.com (Unstable Diffusion NSFW)",
             "https://civitai.com/api/download/models/91623"),
            (
                "зеркало HuggingFace (lllyasviel)",
                "https://huggingface.co/lllyasviel/fav_models/resolve/main/fav/majicmixRealistic_v7.safetensors",
            ),
            (
                "зеркало HuggingFace (digiplay)",
                "https://huggingface.co/digiplay/majicMIX_realistic_v7/resolve/main/majicmixRealistic_v7.safetensors",
            ),
            (
                "Stable Diffusion 1.5 (универсальная, надёжная)",
                "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors",
            ),
        ]
        ok = False
        for name, url in sources:
            print(f"Пробую источник: {name}...")
            tmp = checkpoints / "download_tmp.safetensors"
            if download(url, tmp) and is_valid_checkpoint(tmp):
                tmp.rename(target)
                ok = True
                print(f"✅ Модель сохранена: {target.name} (источник: {name})")
                break
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        if not ok:
            print("❌ Не удалось скачать модель автоматически.")
            print("   Позже сделайте вручную: civitai.com → «explicit» → majicMIX realistic,")
            print("   файл .safetensors → ComfyUI/models/checkpoints/")
    # прописываем NSFW-модель в .env (если файл появился и он настоящий)
    if target.exists() and is_valid_checkpoint(target):
        env = ROOT / ".env"
        if env.exists():
            text = env.read_text(encoding="utf-8")
            lines = []
            for line in text.splitlines():
                if line.startswith("COMFYUI_NSFW_CHECKPOINT="):
                    line = f"COMFYUI_NSFW_CHECKPOINT={target.name}"
                lines.append(line)
            env.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"✅ В .env записано: COMFYUI_NSFW_CHECKPOINT={target.name}")
    print()
    print("Запускать ComfyUI так (каждый раз, когда нужны картинки):")
    print(f'  {comfy_py} "{comfy_dir / "main.py"}" --listen 127.0.0.1 --port 8188 --cpu')
    print()
    # Кладём готовый start_comfyui.bat (с CPU-флагом) прямо в папку ComfyUI —
    # на машинах без NVIDIA-видеокарты без --cpu ComfyUI падает.
    bat = comfy_dir / "start_comfyui.bat"
    try:
        bat.write_text(
            '@echo off\r\ntitle ComfyUI (CPU mode)\r\ncd /d "%~dp0"\r\n'
            'venv\\Scripts\\python.exe main.py --listen 127.0.0.1 --port 8188 --cpu\r\n'
            'pause\r\n',
            encoding="ascii",
        )
        print(f"Готовый файл запуска создан: {bat}")
        print("Двойной клик по нему — и ComfyUI работает (CPU-режим).")
    except OSError as exc:
        print(f"⚠️ Не удалось создать start_comfyui.bat: {exc}")
        print("Скопируйте файл start_comfyui.bat из папки бота в папку ComfyUI.")


# ================================================================== установка всего

def setup() -> None:
    print("=" * 60)
    print("  АВТОУСТАНОВКА всего для бота «Лилит»")
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


def llm_model_installed() -> bool:
    """Проверяет, что модель из .env реально скачана в Ollama."""
    model = ""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("LLM_MODEL="):
                model = line.split("=", 1)[1].strip()
    if not model or not shutil.which("ollama"):
        return False
    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=60, cwd=str(ROOT)
        )
    except Exception:  # noqa: BLE001
        return False
    names = {line.split()[0] for line in out.stdout.splitlines()[1:] if line.strip()}
    return model in names


def llm_speaks_russian(model: str | None = None) -> bool:
    """Проверяет, что модель реально отвечает по-русски (не иероглифами).

    Делает короткий запрос к Ollama и проверяет, что в ответе есть
    русские буквы и нет иероглифов. Если модель отвечает по-китайски
    или не отвечает — возвращает False (установщик предложит другую).
    """
    if model is None:
        model = ""
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("LLM_MODEL="):
                    model = line.split("=", 1)[1].strip()
    if not model or not shutil.which("ollama"):
        return False
    try:
        out = subprocess.run(
            ["ollama", "run", model, "Ответь одним словом: привет"],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
            encoding="utf-8", errors="replace",
        )
        reply = (out.stdout or out.stderr) or ""
    except Exception:  # noqa: BLE001
        return False
    # Русские буквы есть И иероглифов нет
    has_cyrillic = any("\u0400" <= ch <= "\u04FF" for ch in reply)
    has_cjk = any(
        0x4E00 <= ord(ch) <= 0x9FFF or 0x3040 <= ord(ch) <= 0x30FF
        for ch in reply
    )
    return has_cyrillic and not has_cjk


def check_components() -> None:
    """Проверка внешних программ и модели; предлагает автоустановку недостающего."""
    missing = []
    if shutil.which("ollama") is None:
        missing.append("Ollama (мозг бота)")
    if shutil.which("ffmpeg") is None and not (ROOT / PI / "ffmpeg.exe").exists():
        missing.append("ffmpeg (для голоса)")
    if shutil.which("piper") is None and not (ROOT / PI / "piper.exe").exists():
        missing.append("Piper (голос)")
    if not llm_model_installed():
        missing.append("языковая модель (в .env указана, но не скачана)")
    if not missing and not llm_speaks_russian():
        missing.append("проверка: модель отвечает иероглифами или не по-русски")
    # Модель-художник для картинок: если файл есть, но битый — предложить перекачать
    comfy_target = ROOT.parent / "ComfyUI" / "models" / "checkpoints" / "majicmixRealistic_v7.safetensors"
    if comfy_target.exists() and not is_valid_checkpoint(comfy_target):
        missing.append("модель-художник (файл битый — скачаю заново)")
    if not missing:
        print("✅ Все внешние программы и модель на месте.")
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
    print("=" * 60)
    print("  Бот «Лилит» — установщик и запуск")
    print(f"  Версия установщика: {VERSION}")
    print("=" * 60)
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
