"""ORM-модели.

Три таблицы:

* ``users``        — кому разрешено пользоваться API.
* ``applications`` — отслеживаемые отклики на вакансии.
* ``application_events`` — история переходов между этапами, которую можно только
  дописывать.

История — самая интересная часть: она превращает изменяемую колонку ``stage``
в аудируемую сущность, благодаря чему возможны и лента событий, и статистика
«сколько времени до оффера».
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import Priority, Source, Stage, enum_values


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    applications: Mapped[list["Application"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    company: Mapped[str] = mapped_column(String(160), index=True)
    role: Mapped[str] = mapped_column(String(160))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)

    stage: Mapped[Stage] = mapped_column(
        SAEnum(Stage, name="application_stage", values_callable=enum_values),
        default=Stage.APPLIED,
        index=True,
    )
    source: Mapped[Source] = mapped_column(
        SAEnum(Source, name="application_source", values_callable=enum_values),
        default=Source.OTHER,
        index=True,
    )
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, name="application_priority", values_callable=enum_values),
        default=Priority.MEDIUM,
    )

    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
        nullable=False,
    )

    owner: Mapped[User] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.created_at",
    )

    __table_args__ = (
        # Список всегда фильтруется по владельцу и сортируется по свежести.
        Index("ix_applications_owner_created", "owner_id", "created_at"),
        Index("ix_applications_owner_stage", "owner_id", "stage"),
    )


class ApplicationEvent(Base):
    """Неизменяемая запись о переходе между этапами."""

    __tablename__ = "application_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        index=True,
    )

    from_stage: Mapped[Stage | None] = mapped_column(
        SAEnum(Stage, name="application_stage", values_callable=enum_values),
        nullable=True,
    )
    to_stage: Mapped[Stage] = mapped_column(
        SAEnum(Stage, name="application_stage", values_callable=enum_values)
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    )

    application: Mapped[Application] = relationship(back_populates="events")
