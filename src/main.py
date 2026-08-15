"""Точка входа: запуск бота, миграции, воркеры, graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
import signal
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.di import build_app_context
from src.bot.handlers import router as handlers_router
from src.bot.middlewares import (
    ChatTypeMiddleware,
    ContextMiddleware,
    RateLimitMiddleware,
    RegistrationMiddleware,
)
from src.config import PROJECT_ROOT, Settings
from src.miniapp_server import MiniAppServer
from src.utils import ensure_dir
from src.workers import start_workers, stop_workers

ALLOWED_UPDATES = ["message", "callback_query"]

logger = logging.getLogger("project_lady")


def setup_logging(settings: Settings) -> None:
    """Логирование. Содержимое сообщений пользователей в логи не пишется."""
    handlers: list[logging.Handler] = []
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handlers.append(console)
    if settings.log_file is not None:
        log_path = settings.resolve_path(settings.log_file)
        ensure_dir(log_path.parent)
        file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        handlers.append(file_handler)
    logging.basicConfig(level=settings.log_level.upper(), handlers=handlers)


def run_migrations(settings: Settings) -> None:
    """Применяет Alembic-миграции при старте (идемпотентно)."""
    from alembic import command
    from alembic.config import Config

    ensure_dir(settings.resolved_data_dir)
    ini_path = PROJECT_ROOT / "alembic.ini"
    if not ini_path.exists():
        raise RuntimeError(f"alembic.ini не найден: {ini_path}")
    cfg = Config(str(ini_path))
    command.upgrade(cfg, "head")
    logger.info("Миграции применены")


async def _main(settings: Settings) -> None:
    ctx = build_app_context(settings)
    await ctx.db.connect()
    await ctx.warmup()

    # Telegram Mini App (веб-интерфейс профиля/настроек/галереи)
    miniapp = MiniAppServer(
        ctx.db, settings.telegram_token,
        host=settings.miniapp_host, port=settings.miniapp_port,
    )
    miniapp.app["chat"] = ctx.chat  # для /api/chat из мини-приложения
    miniapp.app["image_service"] = ctx.image_service  # для генерации нарядов
    await miniapp.start()

    bot = Bot(settings.telegram_token)
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем команды в меню Telegram (кнопка «Меню»)
    from aiogram.types import BotCommand

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запуск / возрастная проверка"),
            BotCommand(command="app", description="🖤 Открыть мини-приложение Лилит"),
            BotCommand(command="mode", description="Режим: дружеский/флирт/романтика/NSFW"),
            BotCommand(command="photo", description="Нарисовать картинку"),
            BotCommand(command="avatar", description="Показать аватар Лилит"),
            BotCommand(command="style", description="Стиль картинок: реалистичный/аниме"),
            BotCommand(command="voice", description="Голосовые ответы"),
            BotCommand(command="settings", description="Настройки"),
            BotCommand(command="profile", description="Профиль"),
            BotCommand(command="memory", description="Память"),
            BotCommand(command="help", description="Справка"),
        ]
    )
    dp["app_ctx"] = ctx

    # Миделвари и хендлеры
    for event_name in ("message", "callback_query"):
        event_middleware = getattr(dp, event_name).outer_middleware
        event_middleware(ChatTypeMiddleware())
        event_middleware(RateLimitMiddleware(settings))
        event_middleware(ContextMiddleware(ctx))
        event_middleware(RegistrationMiddleware(ctx))
    dp.include_router(handlers_router)

    worker_tasks = start_workers(ctx, bot)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    polling_task = asyncio.create_task(dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES))
    logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    await stop_event.wait()
    logger.info("Останавливаюсь…")
    polling_task.cancel()
    await asyncio.gather(polling_task, return_exceptions=True)
    await stop_workers(worker_tasks)
    await miniapp.stop()
    await ctx.shutdown()
    await bot.session.close()


def main() -> None:
    settings = Settings()
    settings.require_token()
    setup_logging(settings)
    # Миграции до запуска event loop (alembic использует asyncio.run внутри)
    run_migrations(settings)
    try:
        asyncio.run(_main(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
