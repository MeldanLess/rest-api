"""Фикстуры pytest.

Набор тестов выполняется против **настоящей базы PostgreSQL**, а не против SQLite.
SQLite запускается быстрее, но скрывает ровно те ошибки, которые здесь и нужно
ловить: колонки UUID, нативные типы enum, поиск через `ILIKE` и даты с
указанием часового пояса.

Тестовая база создаётся один раз за сессию, накатывается миграциями **Alembic** —
то есть под тестом оказывается и сама миграция, — и очищается между тестами.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models import User
from app.security import hash_password

ROOT = Path(__file__).resolve().parent.parent
TEST_DB_NAME = os.getenv("TEST_DATABASE_NAME", "applytrack_test")


def _url_for(database_name: str) -> str:
    """Подменить имя базы в настроенном адресе подключения."""
    base = get_settings().database_url
    return base.rsplit("/", 1)[0] + "/" + database_name


@pytest.fixture(scope="session")
def engine():
    """Создать тестовую базу, накатить миграции и вернуть движок."""
    admin_url = _url_for("postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB_NAME},
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        admin_engine.dispose()

    test_url = _url_for(TEST_DB_NAME)
    test_engine = create_engine(test_url, pool_pre_ping=True)

    # Накатываем миграции Alembic, а не create_all, чтобы скрипт миграции
    # проверялся при каждом запуске тестов.
    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", test_url.replace("%", "%%"))
    command.upgrade(alembic_config, "head")

    yield test_engine

    test_engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(engine):
    """Очищать все таблицы перед каждым тестом, чтобы тесты не влияли друг на друга."""
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db_session(engine) -> Iterator[Session]:
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with TestingSessionLocal() as session:
        yield session


@pytest.fixture
def client(db_session) -> Iterator[TestClient]:
    """TestClient, у которого база подменена тестовой сессией."""

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user(db_session) -> User:
    """Зарегистрированный пользователь, пароль хранится в виде bcrypt-хеша."""
    account = User(
        email="tester@example.com",
        hashed_password=hash_password("password123"),
        full_name="Тестировщик",
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


@pytest.fixture
def token(client, user) -> str:
    """Действительный токен доступа для `user`."""
    response = client.post(
        "/auth/token", data={"username": user.email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def auth_client(client, token) -> TestClient:
    """Клиент, у которого уже прописан bearer-токен."""
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
