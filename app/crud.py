"""Слой доступа к данным.

Весь SQL живёт здесь, поэтому роутеры занимаются только HTTP, а тесты могут
проверять доменные правила, не выходя в сеть.
"""

import statistics
import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.enums import ALLOWED_TRANSITIONS, Stage
from app.models import Application, ApplicationEvent, User
from app.schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    PipelineStats,
    StageCount,
)


class InvalidTransition(Exception):
    """Бросается, когда смена этапа запрещена доменными правилами."""

    def __init__(self, from_stage: Stage, to_stage: Stage):
        self.from_stage = from_stage
        self.to_stage = to_stage
        super().__init__(
            f"Невозможно перевести отклик из «{from_stage.value}» в «{to_stage.value}»"
        )


class NotFound(Exception):
    """Бросается, когда строки нет или она принадлежит не тому, кто спросил."""


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalar_one_or_none()


def create_user(db: Session, *, email: str, hashed_password: str, full_name: str | None) -> User:
    user = User(email=email.lower(), hashed_password=hashed_password, full_name=full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Отклики
# ---------------------------------------------------------------------------


def create_application(
    db: Session, *, owner_id: uuid.UUID, payload: ApplicationCreate
) -> Application:
    application = Application(owner_id=owner_id, **payload.model_dump())
    db.add(application)
    db.flush()  # получаем сгенерированный id, не завершая транзакцию

    # Само создание — первое событие в истории.
    db.add(
        ApplicationEvent(
            application_id=application.id,
            from_stage=None,
            to_stage=application.stage,
            note="Отклик создан",
        )
    )
    db.commit()
    db.refresh(application)
    return application


def get_application(
    db: Session, *, owner_id: uuid.UUID, application_id: uuid.UUID
) -> Application:
    application = db.get(Application, application_id)
    # 404, а не 403, для чужой строки: 403 подтверждал бы, что такой id
    # существует.
    if application is None or application.owner_id != owner_id:
        raise NotFound("Отклик не найден")
    return application


def list_applications(
    db: Session,
    *,
    owner_id: uuid.UUID,
    stage: Stage | None = None,
    source=None,
    priority=None,
    search: str | None = None,
    active_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Application], int]:
    statement: Select = select(Application).where(Application.owner_id == owner_id)

    if stage is not None:
        statement = statement.where(Application.stage == stage)
    if source is not None:
        statement = statement.where(Application.source == source)
    if priority is not None:
        statement = statement.where(Application.priority == priority)
    if active_only:
        statement = statement.where(
            Application.stage.in_([Stage.APPLIED, Stage.SCREENING, Stage.INTERVIEW])
        )
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Application.company.ilike(pattern),
                Application.role.ilike(pattern),
                Application.location.ilike(pattern),
            )
        )

    total = db.execute(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ).scalar_one()

    rows = db.execute(
        statement.order_by(Application.created_at.desc(), Application.id)
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return list(rows), total


def update_application(
    db: Session, *, application: Application, payload: ApplicationUpdate
) -> Application:
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(application, field, value)
    db.commit()
    db.refresh(application)
    return application


def delete_application(db: Session, *, application: Application) -> None:
    db.delete(application)
    db.commit()


def change_stage(
    db: Session,
    *,
    application: Application,
    to_stage: Stage,
    note: str | None = None,
) -> Application:
    """Переводит отклик на новый этап и записывает переход."""
    from_stage = application.stage

    if from_stage != to_stage:
        allowed = ALLOWED_TRANSITIONS.get(from_stage, set())
        if to_stage not in allowed:
            raise InvalidTransition(from_stage, to_stage)

    application.stage = to_stage
    db.add(
        ApplicationEvent(
            application_id=application.id,
            from_stage=from_stage,
            to_stage=to_stage,
            note=note,
        )
    )
    db.commit()
    db.refresh(application)
    return application


def list_events(
    db: Session, *, application: Application
) -> list[ApplicationEvent]:
    # `id` — тай-брейкер, чтобы порядок был полным даже если два события
    # попадут в одну секунду.
    return list(
        db.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application.id)
            .order_by(ApplicationEvent.created_at, ApplicationEvent.id)
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------


def pipeline_stats(db: Session, *, owner_id: uuid.UUID) -> PipelineStats:
    """Собирает сводку по воронке откликов.

    Намеренно считается на Python, а не одним большим SQL-запросом: данные — это
    отклики одного человека (сотни строк), и читаемый Python здесь стоит больше,
    чем экономия миллисекунд на запросе, который и так выполняется мгновенно.
    Логика агрегации при этом тестируется отдельно.
    """
    applications = list(
        db.execute(
            select(Application).where(Application.owner_id == owner_id)
        )
        .scalars()
        .all()
    )

    by_stage_counts: dict[Stage, int] = {}
    by_source_counts: dict[str, int] = {}
    active = 0
    terminal = 0

    for application in applications:
        by_stage_counts[application.stage] = by_stage_counts.get(application.stage, 0) + 1
        by_source_counts[application.source.value] = (
            by_source_counts.get(application.source.value, 0) + 1
        )
        if application.stage.is_active:
            active += 1
        elif application.stage.is_terminal:
            terminal += 1

    total = len(applications)
    offers = by_stage_counts.get(Stage.OFFER, 0)

    # Время до первого ответа: создание → первое записанное событие.
    response_rows = db.execute(
        select(
            Application.created_at.label("created_at"),
            func.min(ApplicationEvent.created_at).label("first_event_at"),
        )
        .join(ApplicationEvent, ApplicationEvent.application_id == Application.id)
        .where(Application.owner_id == owner_id)
        .group_by(Application.id)
    ).all()

    response_days = [
        (row.first_event_at - row.created_at).total_seconds() / 86400
        for row in response_rows
        if row.first_event_at is not None and row.created_at is not None
    ]

    # Время до оффера: создание → событие, которым отклик перешёл в оффер.
    offer_rows = db.execute(
        select(Application.created_at.label("created_at"), ApplicationEvent.created_at.label("at"))
        .join(ApplicationEvent, ApplicationEvent.application_id == Application.id)
        .where(
            Application.owner_id == owner_id,
            ApplicationEvent.to_stage == Stage.OFFER,
        )
    ).all()

    offer_days = [
        (row.at - row.created_at).total_seconds() / 86400
        for row in offer_rows
        if row.at is not None and row.created_at is not None
    ]

    def median_or_none(values: list[float]) -> float | None:
        return round(statistics.median(values), 2) if values else None

    return PipelineStats(
        total=total,
        active=active,
        terminal=terminal,
        by_stage=[
            StageCount(stage=stage, count=count)
            for stage, count in sorted(by_stage_counts.items(), key=lambda item: item[0].value)
        ],
        by_source=by_source_counts,
        offer_rate=round(offers / total, 3) if total else 0.0,
        median_days_to_first_response=median_or_none(response_days),
        median_days_to_offer=median_or_none(offer_days),
    )
