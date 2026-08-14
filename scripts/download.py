"""Загрузка файла с SSL-сертификатами certifi (обходит ошибки сертификатов Windows).

Используется автоустановщиком (launcher.py) для скачивания голосовых моделей
и ffmpeg. Запускается venv-питоном, в котором установлен certifi:
    .venv\\Scripts\\python.exe scripts\\download.py <url> <куда_сохранить>
"""
from __future__ import annotations

import shutil
import ssl
import sys
import urllib.request

url, dest = sys.argv[1], sys.argv[2]

try:
    import certifi

    context = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    context = ssl.create_default_context()

request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(request, context=context, timeout=120) as response, open(dest, "wb") as out:
    shutil.copyfileobj(response, out)
print("downloaded", dest)
