"""Сборка автономного офлайн-приложения новеллы «Лилит» (без бота и интернета).

Генерирует в novel_app/web/:
- scenarios.js  — все сценарии (JSON) как JS-переменная (для file:// без fetch);
- index.html, style.css, app.js — автономный интерфейс новеллы (18+ гейт,
  меню сценариев, прогресс в localStorage);
- images/ — фото сцен, скопированные из assets/gallery.

Запуск:  python3 scripts/build_novel_offline.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.novel import SCENARIOS  # noqa: E402

WEB_DIR = ROOT / "novel_app" / "web"
IMAGES_DIR = WEB_DIR / "images"
GALLERY = ROOT / "assets" / "gallery"


def main() -> None:
    # Не удаляем всю папку: index.html/style.css/app.js пишутся вручную.
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(IMAGES_DIR, ignore_errors=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Собираем данные сценариев + список фото
    payload: dict = {"scenarios": {}}
    images: set[str] = set()
    for sid, sc in SCENARIOS.items():
        payload["scenarios"][sid] = {
            "title": sc["title"],
            "subtitle": sc["subtitle"],
            "start": sc["start"],
            "nodes": sc["nodes"],
        }
        for node in sc["nodes"].values():
            images.add(node["image"])

    # 2. Копируем фото
    for name in sorted(images):
        src = GALLERY / name
        if not src.exists():
            raise SystemExit(f"Нет фото: {src}")
        shutil.copy2(src, IMAGES_DIR / name)
    print(f"Скопировано фото: {len(images)}")

    # 3. scenarios.js — данные как JS-переменная (file:// не умеет fetch)
    js = "/* Автогенерация: scripts/build_novel_offline.py */\n"
    js += "window.NOVEL_DATA = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n"
    (WEB_DIR / "scenarios.js").write_text(js, encoding="utf-8")
    print(f"scenarios.js: {len(js)//1024} КБ")

    print("Готово:", WEB_DIR)


if __name__ == "__main__":
    main()
