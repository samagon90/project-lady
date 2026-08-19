"""Пакетная генерация 100 изображений Лилит (через ComfyUI).

Запуск (в Colab после установки ComfyUI):
    python scripts/generate_batch.py --count 100 --out /content/lilith_gallery

Или через бота: каждая картинка = задача в очереди (как /photo).
Промпты: 5 поз x 5 эмоций x 4 степени одежды = 100 комбинаций,
всегда с якорем внешности Лилит (хвостики, рыжая, веснушки).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import Settings  # noqa: E402
from src.providers.base import ImageRequest  # noqa: E402
from src.providers.comfyui import ComfyUIProvider  # noqa: E402

# Якорь внешности Лилит (всегда)
LILITH_ANCHOR = (
    "1girl, red hair in two pigtails with black ribbons, green eyes, "
    "pale skin, freckles, high cheekbones, 24 years old, "
    "tall, slim, adult woman, "
    "ALWAYS wears thigh-high stockings with garter belt (she never "
    "takes them off — even in lingerie, at home, at night)"
)

POSES = [
    "standing pose, full body",
    "sitting on a chair, legs crossed",
    "lying on a bed, relaxed",
    "leaning against a wall, playful",
    "walking toward viewer, dynamic",
]

EMOTIONS = [
    ("neutral", "calm neutral expression"),
    ("happy", "bright joyful smile"),
    ("flirt", "playful flirtatious wink"),
    ("passion", "passionate seductive gaze"),
    ("tender", "soft tender loving look"),
]

OUTFITS = [
    ("fully_dressed", "white blouse, pleated plaid mini skirt, thigh-high stockings, high heels"),
    ("lingerie", "black lace lingerie set, thigh-high stockings, garter belt, high heels"),
    ("topless", "nude topless, black thigh-high stockings only, arms slightly covering chest"),
    ("nude", "fully nude, artistic nude, thigh-high stockings, tasteful"),
]


def build_prompt(pose: str, emotion: str, outfit: str) -> str:
    return (
        f"{LILITH_ANCHOR}, {emotion}, {outfit}, {pose}, "
        "dark romantic background, cinematic lighting, "
        "semi-realistic digital art, detailed face, 8k"
    )


async def generate_batch(count: int, out_dir: Path) -> None:
    settings = Settings(_env_file=None)
    settings.comfyui_workflow_path = ROOT / "workflows" / "comfyui_lilith_ipadapter.json"
    provider = ComfyUIProvider(
        settings.comfyui_base_url,
        settings.resolve_path(settings.comfyui_workflow_path),
        checkpoint=settings.comfyui_checkpoint,
        nsfw_checkpoint=settings.comfyui_nsfw_checkpoint,
        reference_image=settings.resolve_path(
            settings.comfyui_reference_image or Path("assets/emotions/lilith_playful.png")
        ),
        timeout_seconds=settings.comfyui_timeout_seconds,
    )
    out_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 — скрипт, не сервер

    combos = []
    for pose in POSES:
        for emotion_name, _emotion_desc in EMOTIONS:
            for _outfit_name, outfit_desc in OUTFITS:
                combos.append((pose, emotion_name, outfit_desc))
    # 100 = первые 100 комбинаций (5*5*4=100 ровно)
    combos = combos[:count]

    print(f"Генерация {len(combos)} изображений -> {out_dir}")
    done = 0
    for i, (pose, emo, outfit) in enumerate(combos, 1):
        prompt = build_prompt(pose, emo, outfit)
        request = ImageRequest(
            prompt=prompt,
            negative_prompt=settings and "worst quality, low quality, bad anatomy, bad hands, "
            "extra fingers, deformed, blurry, watermark, text, child, teenager, underage",
            width=512,
            height=768,
            steps=30,
            cfg=7.0,
            seed=-1,
            nsfw=(outfit != "fully_dressed"),
        )
        try:
            images = await provider.generate(request)
            if images:
                path = out_dir / f"lilith_{i:03d}_{emo}_{outfit.replace(' ', '_')}.png"
                path.write_bytes(images[0])
                done += 1
                print(f"[{i}/{len(combos)}] OK {path.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(combos)}] ❌ {exc}")
        await asyncio.sleep(0.5)
    print(f"Готово: {done}/{len(combos)} изображений в {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch generate Lilith images")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out", type=str, default="/content/lilith_gallery")
    args = parser.parse_args()
    asyncio.run(generate_batch(args.count, Path(args.out)))


if __name__ == "__main__":
    main()
