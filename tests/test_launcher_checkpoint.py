"""Тесты валидации checkpoint-файлов (защита от HTML вместо модели)."""
from __future__ import annotations

import json
import struct

import launcher


def _make_safetensors(path, *, good: bool) -> None:
    keys = (
        {
            "model.diffusion_model.foo": [0],
            "cond_stage_model.bar": [0],
            "first_stage_model.baz": [0],
        }
        if good
        else {"first_stage_model.baz": [0]}  # только VAE — не полный checkpoint
    )
    header = json.dumps(keys).encode()
    path.write_bytes(struct.pack("<Q", len(header)) + header)


def test_valid_checkpoint_detected(tmp_path) -> None:
    launcher.MIN_CHECKPOINT_BYTES = 0
    good = tmp_path / "good.safetensors"
    _make_safetensors(good, good=True)
    assert launcher.is_valid_checkpoint(good)


def test_vae_only_not_detected(tmp_path) -> None:
    launcher.MIN_CHECKPOINT_BYTES = 0
    vae = tmp_path / "vae.safetensors"
    _make_safetensors(vae, good=False)
    assert not launcher.is_valid_checkpoint(vae)


def test_html_page_not_detected(tmp_path) -> None:
    launcher.MIN_CHECKPOINT_BYTES = 0
    html = tmp_path / "page.safetensors"
    html.write_bytes(b"<!DOCTYPE html><html><body>challenge</body></html>")
    assert not launcher.is_valid_checkpoint(html)


def test_small_file_not_detected(tmp_path) -> None:
    launcher.MIN_CHECKPOINT_BYTES = 50 * 1024 * 1024
    small = tmp_path / "small.safetensors"
    small.write_bytes(b"\x00" * 1024)
    assert not launcher.is_valid_checkpoint(small)
