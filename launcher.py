"""Запуск бота «Лея» на Windows — без знания программирования.

Этот скрипт запускается файлом start_windows.bat и делает всё сам:
1) создаёт окружение и ставит зависимости (в первый раз 2-5 минут);
2) проверяет файл настроек .env и сам открывает Блокнот, чтобы вписать токен;
3) применяет миграции базы данных;
4) запускает бота.

Русские сообщения печатает Python — поэтому на любом Windows они
отображаются корректно (в отличие от текста внутри .bat-файла).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run(args) -> None:
    subprocess.run([str(a) for a in args], cwd=str(ROOT), check=False)


# ---------------------------------------------------------------- установка

def venv_ready() -> bool:
    return VENV_PY.exists()


def create_venv() -> None:
    print("Шаг 1 из 3: готовлю окружение... (первый запуск, 2-5 минут)")
    run([sys.executable, "-m", "venv", str(ROOT / ".venv")])


def install_deps() -> None:
    print("Устанавливаю программы бота... (ещё 1-3 минуты)")
    run([VENV_PY, "-m", "pip", "install", "-q", "-e", "."])


# ---------------------------------------------------------------- настройки

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
    """Открывает .env в Блокноте и ждёт, пока пользователь сохранит и закроет."""
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


# ---------------------------------------------------------------- запуск

def migrate() -> None:
    print("Шаг 2 из 3: настраиваю базу данных...")
    run([VENV_PY, "-m", "alembic", "upgrade", "head"])


def run_bot() -> None:
    print("Шаг 3 из 3: запускаю бота...")
    print()
    print("Бот работает! НЕ ЗАКРЫВАЙТЕ это окно.")
    print("Чтобы остановить бота — закройте это окно (или нажмите Ctrl+C).")
    print()
    run([VENV_PY, "-m", "src.main"])
    print("Бот остановлен.")


# ---------------------------------------------------------------- main

def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "start"
    if not venv_ready():
        create_venv()
    install_deps()
    if mode == "check":
        run([VENV_PY, "scripts", "doctor.py"])
        return
    if not ensure_env():
        input("Нажмите Enter, чтобы закрыть окно...")
        sys.exit(1)
    migrate()
    run_bot()


if __name__ == "__main__":
    main()
