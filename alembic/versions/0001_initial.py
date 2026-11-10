"""Начальная схема

Создаёт три типа enum в PostgreSQL, а также таблицы users, applications и
application_events.

Идентификатор ревизии: 0001_initial
Предыдущая ревизия:
Дата создания: 2026-11-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STAGE_VALUES = ("applied", "screening", "interview", "offer", "rejected", "withdrawn")
SOURCE_VALUES = (
    "hh",
    "linkedin",
    "telegram",
    "referral",
    "university",
    "company_site",
    "other",
)
PRIORITY_VALUES = ("low", "medium", "high")


def upgrade() -> None:
    bind = op.get_bind()

    # Типы enum создаём явно, а колонки потом ссылаются на них с
    # create_type=False. Если дать SQLAlchemy создать их на месте, вторая
    # таблица с тем же типом упадёт с ошибкой.
    postgresql.ENUM(*STAGE_VALUES, name="application_stage").create(bind, checkfirst=True)
    postgresql.ENUM(*SOURCE_VALUES, name="application_source").create(bind, checkfirst=True)
    postgresql.ENUM(*PRIORITY_VALUES, name="application_priority").create(bind, checkfirst=True)

    stage_enum = postgresql.ENUM(
        *STAGE_VALUES, name="application_stage", create_type=False
    )
    source_enum = postgresql.ENUM(
        *SOURCE_VALUES, name="application_source", create_type=False
    )
    priority_enum = postgresql.ENUM(
        *PRIORITY_VALUES, name="application_priority", create_type=False
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=160), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("location", sa.String(length=160), nullable=True),
        sa.Column("stage", stage_enum, nullable=False),
        sa.Column("source", source_enum, nullable=False),
        sa.Column("priority", priority_enum, nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_step_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applications_owner_id", "applications", ["owner_id"])
    op.create_index("ix_applications_company", "applications", ["company"])
    op.create_index("ix_applications_stage", "applications", ["stage"])
    op.create_index("ix_applications_source", "applications", ["source"])
    op.create_index(
        "ix_applications_owner_created", "applications", ["owner_id", "created_at"]
    )
    op.create_index(
        "ix_applications_owner_stage", "applications", ["owner_id", "stage"]
    )

    op.create_table(
        "application_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_stage", stage_enum, nullable=True),
        sa.Column("to_stage", stage_enum, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_events_application_id", "application_events", ["application_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_application_events_application_id", table_name="application_events")
    op.drop_table("application_events")

    op.drop_index("ix_applications_owner_stage", table_name="applications")
    op.drop_index("ix_applications_owner_created", table_name="applications")
    op.drop_index("ix_applications_source", table_name="applications")
    op.drop_index("ix_applications_stage", table_name="applications")
    op.drop_index("ix_applications_company", table_name="applications")
    op.drop_index("ix_applications_owner_id", table_name="applications")
    op.drop_table("applications")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    postgresql.ENUM(name="application_priority").drop(bind, checkfirst=True)
    postgresql.ENUM(name="application_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="application_stage").drop(bind, checkfirst=True)
