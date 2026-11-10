"""Окружение Alembic.

Адрес базы берётся из настроек приложения, а не из `alembic.ini`, поэтому
миграции всегда нацелены на ту же базу, которую использует само приложение.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Делаем пакет `app` импортируемым, когда Alembic запускают из корня репозитория.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import models  # noqa: F401  (импорт нужен ради метаданных)
from app.config import get_settings
from app.database import Base

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers=False` — иначе Alembic выключит все логгеры,
    # которых нет в `alembic.ini`, в том числе логгеры самого приложения.
    #
    # Это не видно, пока миграции запускают отдельной командой, но больно,
    # когда их выполняют в том же процессе, что и приложение (так делает
    # набор тестов): после `upgrade head` приложение продолжает работать, но
    # молчит — и неудачный вход не попадает в лог.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Адрес можно передать явно — так делает набор тестов, чтобы накатить миграции
# на одноразовую базу. Иначе он берётся из настроек приложения.
if not config.get_main_option("sqlalchemy.url", None):
    # `%%` экранирует знак процента для интерполяции configparser.
    config.set_main_option(
        "sqlalchemy.url", get_settings().database_url.replace("%", "%%")
    )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Печатать SQL в вывод скрипта, а не выполнять его на базе."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Выполнить миграции по живому подключению к базе."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
