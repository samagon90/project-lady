"""Alembic environment (async). URL берётся из настроек приложения."""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool, StaticPool

# Корень проекта в sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Settings  # noqa: E402
from src.database.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL из .env, иначе дефолт из alembic.ini
settings = Settings(_env_file=str(ROOT / ".env"))
db_url = settings.database_url
if db_url.startswith("sqlite"):
    db_path = db_url.removeprefix("sqlite+aiosqlite:///")
    if not db_path.startswith("/") and not db_path.startswith("file:"):
        (ROOT / db_path).parent.mkdir(parents=True, exist_ok=True)
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def _pool_args():
    if db_url.startswith("sqlite"):
        if ":memory:" in db_url:
            return {"poolclass": StaticPool}
        return {"poolclass": NullPool}
    return {}


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        **{},
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
