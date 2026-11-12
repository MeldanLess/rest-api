"""Схемы Pydantic — форма каждого запроса и ответа.

Это публичный контракт API. ORM-модели остаются внутренними: переименование
колонки не должно молча менять JSON, на который полагаются клиенты.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.config import get_settings
from app.enums import Priority, Source, Stage
from app.security import MAX_PASSWORD_BYTES

settings = get_settings()


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Пользователи и аутентификация
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(
        min_length=settings.password_min_length,
        max_length=MAX_PASSWORD_BYTES,
        description="Пароль в открытом виде; хранится только bcrypt-хеш.",
    )
    full_name: str | None = Field(default=None, max_length=120)

    @field_validator("password")
    @classmethod
    def _password_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be blank")
        return value


class UserRead(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenWithUser(Token):
    user: UserRead


# ---------------------------------------------------------------------------
# Отклики
# ---------------------------------------------------------------------------


class ApplicationBase(BaseModel):
    company: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=160)
    url: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=160)
    source: Source = Source.OTHER
    priority: Priority = Priority.MEDIUM
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", max_length=8)
    # Заметка ограничена: без предела одна строка может занять мегабайты, и
    # база растёт от одного запроса.
    notes: str | None = Field(default=None, max_length=5000)
    next_step_at: datetime | None = None


class ApplicationCreate(ApplicationBase):
    stage: Stage = Stage.APPLIED


class ApplicationUpdate(BaseModel):
    """Все поля необязательные — PATCH меняет только то, что прислали."""

    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(default=None, min_length=1, max_length=160)
    role: str | None = Field(default=None, min_length=1, max_length=160)
    url: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=160)
    source: Source | None = None
    priority: Priority | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    notes: str | None = None
    next_step_at: datetime | None = None


class ApplicationRead(ORMModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    company: str
    role: str
    url: str | None = None
    location: str | None = None
    stage: Stage
    source: Source
    priority: Priority
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str
    notes: str | None = None
    next_step_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StageChange(BaseModel):
    """Тело запроса на смену этапа."""

    to_stage: Stage
    note: str | None = None


class ApplicationEventRead(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    from_stage: Stage | None = None
    to_stage: Stage
    note: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Постраничный вывод и статистика
# ---------------------------------------------------------------------------


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class StageCount(BaseModel):
    stage: Stage
    count: int


class PipelineStats(BaseModel):
    """Сводка по воронке откликов."""

    total: int
    active: int
    terminal: int
    by_stage: list[StageCount]
    by_source: dict[str, int]
    offer_rate: float = Field(
        description="Доля откликов, дошедших до оффера (0-1)."
    )
    median_days_to_first_response: float | None = None
    median_days_to_offer: float | None = None


class Health(BaseModel):
    status: str
    database: str
    version: str
