"""Inline-клавиатуры."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def age_gate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Мне есть 18 лет", callback_data="age:ok"),
                InlineKeyboardButton(text="🚪 Выйти", callback_data="age:exit"),
            ]
        ]
    )


def base_consent_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласен(на)", callback_data="consent:base:ok")],
            [InlineKeyboardButton(text="🚪 Выйти", callback_data="consent:base:no")],
        ]
    )


def nsfw_consent_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔞 Принимаю условия NSFW", callback_data="consent:nsfw:ok")],
            [InlineKeyboardButton(text="🙅 Нет, спасибо", callback_data="consent:nsfw:no")],
        ]
    )


def nsfw_after_consent_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔞 Включить NSFW-режим", callback_data="mode:set:3"),
                InlineKeyboardButton(text="⏳ Позже", callback_data="consent:nsfw:later"),
            ]
        ]
    )


def mode_kb(current_mode: int) -> InlineKeyboardMarkup:
    rows = []
    for mode in range(4):
        label = {0: "🤝 Дружеский", 1: "😉 Лёгкий флирт", 2: "💞 Романтический", 3: "🔞 NSFW"}[mode]
        mark = " ✅" if mode == current_mode else ""
        rows.append([InlineKeyboardButton(text=f"{label}{mark}", callback_data=f"mode:set:{mode}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Имя", callback_data="settings:name")],
            [InlineKeyboardButton(text="💬 Обращение (ты/вы)", callback_data="settings:address")],
            [InlineKeyboardButton(text="🏳️ Местоимения", callback_data="settings:pronouns")],
            [InlineKeyboardButton(text="❤️ Интересы", callback_data="settings:interests")],
            [InlineKeyboardButton(text="🚧 Границы и запретные темы", callback_data="settings:boundaries")],
            [InlineKeyboardButton(text="✅ Готово", callback_data="settings:done")],
        ]
    )


def voice_kb(enabled: bool) -> InlineKeyboardMarkup:
    state = "🔊 Включено" if enabled else "🔇 Выключено"
    action = "Выключить" if enabled else "Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🎙 {state} (нажми, чтобы {action.lower()})", callback_data="voice:toggle")]
        ]
    )


def confirm_kb(kind: str) -> InlineKeyboardMarkup:
    """kind: reset | forget"""
    prefix = {"reset": "reset", "forget": "forget"}[kind]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"{prefix}:yes"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"{prefix}:no"),
            ]
        ]
    )


def photo_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="photo:cancel")]]
    )
