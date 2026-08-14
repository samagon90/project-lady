"""FSM-состояния для многошаговых операций."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SettingsStates(StatesGroup):
    name = State()  # имя и обращение
    address_term = State()  # ты/вы
    pronouns = State()  # местоимения
    interests = State()  # интересы
    boundaries = State()  # границы и запретные темы


class PhotoStates(StatesGroup):
    prompt = State()  # ожидание текста запроса для /photo


class ConfirmStates(StatesGroup):
    reset = State()  # подтверждение /reset
    forget_me = State()  # подтверждение /forget_me
