"""Тесты хранения: безопасные имена, очистка временных файлов."""

from __future__ import annotations

import os
import time
from datetime import timedelta

from src.bot.di import AppContext


async def test_temp_names_are_uuid_based(ctx: AppContext) -> None:
    p1 = ctx.storage.new_temp_path("voice", ".wav")
    p2 = ctx.storage.new_temp_path("voice", ".wav")
    assert p1 != p2
    assert p1.name.startswith("voice_") and p1.name.endswith(".wav")
    assert p1.parent == ctx.storage.temp_dir
    # имена содержат только hex-uuid — никакого пользовательского ввода
    middle = p1.name.removeprefix("voice_").removesuffix(".wav")
    assert len(middle) == 32
    int(middle, 16)  # не бросит исключение


async def test_cleanup_expired_removes_only_old(ctx: AppContext) -> None:
    old = ctx.storage.new_temp_path("voice", ".wav")
    fresh = ctx.storage.new_temp_path("voice", ".wav")
    old.write_bytes(b"x")
    fresh.write_bytes(b"y")
    old_time = time.time() - 3600 * 48  # 2 дня назад
    os.utime(old, (old_time, old_time))

    removed = ctx.storage.cleanup_expired(timedelta(hours=24))

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


async def test_remove_many_ignores_missing(ctx: AppContext) -> None:
    p = ctx.storage.new_temp_path("img", ".png")
    p.write_bytes(b"data")
    ctx.storage.remove_many([p, ctx.storage.new_temp_path("img", ".png")])
    assert not p.exists()


async def test_unlink_if_exists_only_within_data_dir(ctx: AppContext) -> None:
    # файл внутри data_dir удаляется
    inside = ctx.storage.new_temp_path("img", ".png")
    inside.write_bytes(b"data")
    ctx.storage.unlink_if_exists(str(inside))
    assert not inside.exists()

    # путь вне data_dir не трогается
    outside = ctx.storage.data_dir.parent / "outside.txt"
    outside.write_text("secret")
    ctx.storage.unlink_if_exists(str(outside))
    assert outside.exists()
