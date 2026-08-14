"""Пакет хендлеров."""

from __future__ import annotations

from aiogram import Router

from src.bot.handlers import chat, commands, common, consent

router = Router()
router.include_router(common.router)
router.include_router(consent.router)
router.include_router(commands.router)
router.include_router(chat.router)
