#!/usr/bin/env bash
# Проверка готовности окружения (macOS / Linux).
# Перетащите этот файл в окно Терминала и нажмите Enter.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    echo "Сначала запустите start.sh"
    exit 1
fi
.venv/bin/python scripts/doctor.py
