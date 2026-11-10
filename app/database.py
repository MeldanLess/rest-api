"""Движок базы данных, фабрика сессий и декларативная база."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    # Переиспользуем соединения до того, как сервер (или прокси перед ним) их
    # закроет. Дешёвая страховка от "server closed the connection unexpectedly".
    pool_pre_ping=True,
    echo=settings.sql_echo,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    # Атрибуты остаются usable после commit без лишнего SELECT.
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Декларативная база для всех ORM-моделей."""


def get_db() -> Generator[Session, None, None]:
    """Зависимость FastAPI: отдаёт сессию и всегда её закрывает."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
