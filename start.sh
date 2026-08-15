#!/usr/bin/env bash
# Запуск бота «Лилит» для macOS / Linux.
# Как пользоваться (без знания программирования):
#   1. Откройте «Терминал» (macOS: Finder -> Программы -> Утилиты -> Терминал)
#   2. Перетащите этот файл (start.sh) мышкой в окно Терминала и нажмите Enter
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  Запуск бота «Лилит»"
echo "============================================"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ОШИБКА] Python не найден."
    echo "Установите его с сайта https://www.python.org/downloads/ и повторите."
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Шаг 1 из 3: готовим окружение... (первый запуск, подождите)"
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -e ".[dev]"

if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "[ВАЖНО] Создан файл настроек .env, но он ещё пустой."
    echo "Откройте файл .env любым текстовым редактором и впишите"
    echo "после TELEGRAM_TOKEN= свой токен от BotFather (без пробелов)."
    echo "Затем запустите start.sh снова."
    exit 1
fi

echo "Шаг 2 из 3: настраиваем базу данных..."
.venv/bin/python -m alembic upgrade head

echo "Шаг 3 из 3: запускаем бота..."
echo
echo "Бот работает! Не закрывайте это окно. Остановка: Ctrl+C"
echo
.venv/bin/python -m src.main
