"""Агрегированная статистика по воронке и проверка состояния."""

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.crud import pipeline_stats
from app.deps import CurrentUser, DbSession
from app.schemas import Health, PipelineStats

router = APIRouter(tags=["stats"])
settings = get_settings()


@router.get(
    "/stats/pipeline",
    response_model=PipelineStats,
    summary="Статистика по воронке откликов",
    description=(
        "Количество откликов по этапам и источникам, доля дошедших до оффера "
        "и медианное время до первого ответа и до оффера."
    ),
)
def read_pipeline_stats(current_user: CurrentUser, db: DbSession) -> PipelineStats:
    return pipeline_stats(db, owner_id=current_user.id)


@router.get("/health", response_model=Health, summary="Проверка состояния")
def health(db: DbSession) -> Health:
    """Живость и готовность в одном месте.

    Сообщает о базе как "up" или "down", а не падает с ошибкой, чтобы система
    мониторинга могла отличить «процесс жив, но база недоступна» от «процесса
    нет».
    """
    try:
        db.execute(text("SELECT 1"))
        database = "up"
    except Exception:
        # Проверка состояния не должна бросать: она обязана сообщить о сломанной
        # базе, а не уронить процесс, который об этом сообщает.
        database = "down"

    return Health(
        status="ok" if database == "up" else "degraded",
        database=database,
        version=settings.version,
    )
