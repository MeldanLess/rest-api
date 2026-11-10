"""Отклики на вакансии — основной ресурс."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status

from app import crud
from app.deps import CurrentUser, DbSession
from app.enums import Priority, Source, Stage
from app.schemas import (
    ApplicationCreate,
    ApplicationEventRead,
    ApplicationRead,
    ApplicationUpdate,
    Page,
    StageChange,
)

router = APIRouter(prefix="/applications", tags=["applications"])
logger = logging.getLogger(__name__)


@router.get(
    "",
    response_model=Page[ApplicationRead],
    summary="Список откликов",
    description=(
        "Возвращает отклики текущего пользователя, сначала самые свежие. Поддерживает "
        "фильтры по этапу, источнику и приоритету, полнотекстовый поиск по "
        "компании, должности и городу, а также постраничный вывод."
    ),
)
def list_applications(
    current_user: CurrentUser,
    db: DbSession,
    stage: Stage | None = Query(default=None, description="Фильтр по этапу воронки"),
    source: Source | None = Query(default=None, description="Фильтр по источнику вакансии"),
    priority: Priority | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120, description="Полнотекстовый поиск"),
    active_only: bool = Query(default=False, description="Только активные этапы"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[ApplicationRead]:
    items, total = crud.list_applications(
        db,
        owner_id=current_user.id,
        stage=stage,
        source=source,
        priority=priority,
        search=q,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return Page[ApplicationRead](
        items=[ApplicationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать отклик",
)
def create_application(
    payload: ApplicationCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> ApplicationRead:
    application = crud.create_application(db, owner_id=current_user.id, payload=payload)
    logger.info(
        "Отклик создан",
        extra={
            "event": "application.created",
            "application_id": str(application.id),
            "company": application.company,
        },
    )
    return ApplicationRead.model_validate(application)


@router.get(
    "/{application_id}",
    response_model=ApplicationRead,
    summary="Прочитать один отклик",
)
def read_application(
    application_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> ApplicationRead:
    try:
        application = crud.get_application(
            db, owner_id=current_user.id, application_id=application_id
        )
    except crud.NotFound:
        # `from None`, потому что отсутствующая строка — это ожидаемый исход,
        # а не ошибка, для которой стоит показывать стектрейс.
        raise HTTPException(status_code=404, detail="Отклик не найден") from None
    return ApplicationRead.model_validate(application)


@router.patch(
    "/{application_id}",
    response_model=ApplicationRead,
    summary="Обновить отклик",
)
def update_application(
    application_id: uuid.UUID,
    payload: ApplicationUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> ApplicationRead:
    """Частичное обновление — меняются только те поля, что есть в теле запроса.

    Этап здесь сознательно *не* меняется: у него есть собственный эндпоинт,
    чтобы каждое изменение попадало в историю.
    """
    try:
        application = crud.get_application(
            db, owner_id=current_user.id, application_id=application_id
        )
    except crud.NotFound:
        raise HTTPException(status_code=404, detail="Отклик не найден") from None

    updated = crud.update_application(db, application=application, payload=payload)
    return ApplicationRead.model_validate(updated)


@router.delete(
    "/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить отклик",
)
def delete_application(
    application_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        application = crud.get_application(
            db, owner_id=current_user.id, application_id=application_id
        )
    except crud.NotFound:
        raise HTTPException(status_code=404, detail="Отклик не найден") from None

    crud.delete_application(db, application=application)
    logger.info(
        "Отклик удалён",
        extra={
            "event": "application.deleted",
            "application_id": str(application_id),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{application_id}/stage",
    response_model=ApplicationRead,
    summary="Перевести отклик на другой этап",
    description=(
        "Записывает переход между этапами в историю отклика. Переходы, которые "
        "запрещены доменными правилами, возвращают 409."
    ),
)
def change_stage(
    application_id: uuid.UUID,
    payload: StageChange,
    current_user: CurrentUser,
    db: DbSession,
) -> ApplicationRead:
    try:
        application = crud.get_application(
            db, owner_id=current_user.id, application_id=application_id
        )
    except crud.NotFound:
        raise HTTPException(status_code=404, detail="Отклик не найден") from None

    # Запоминаем этап до изменения: `crud.change_stage` меняет строку, поэтому
    # чтение `application.stage` после вызова дало бы новое значение дважды.
    from_stage = application.stage

    try:
        updated = crud.change_stage(
            db,
            application=application,
            to_stage=payload.to_stage,
            note=payload.note,
        )
    except crud.InvalidTransition as error:
        logger.info(
            "Переход между этапами отклонён",
            extra={
                "event": "application.stage_rejected",
                "application_id": str(application_id),
                "from_stage": from_stage.value,
                "to_stage": payload.to_stage.value,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    logger.info(
        "Этап изменён",
        extra={
            "event": "application.stage_changed",
            "application_id": str(application_id),
            "from_stage": from_stage.value,
            "to_stage": payload.to_stage.value,
        },
    )
    return ApplicationRead.model_validate(updated)


@router.get(
    "/{application_id}/events",
    response_model=list[ApplicationEventRead],
    summary="История отклика",
)
def list_events(
    application_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[ApplicationEventRead]:
    try:
        application = crud.get_application(
            db, owner_id=current_user.id, application_id=application_id
        )
    except crud.NotFound:
        raise HTTPException(status_code=404, detail="Отклик не найден") from None

    events = crud.list_events(db, application=application)
    return [ApplicationEventRead.model_validate(event) for event in events]
