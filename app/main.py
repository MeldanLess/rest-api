"""Точка входа приложения.

Запуск:  uvicorn app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.logging_config import RequestContextMiddleware, configure_logging, get_request_id
from app.routers import applications, auth, stats

settings = get_settings()

DESCRIPTION = """
Небольшой, но хорошо документированный REST API для учёта откликов на вакансии.

**Что он показывает**

* OAuth2 password flow с bcrypt-хешами паролей и JWT access-токенами
* Реляционное моделирование на SQLAlchemy 2.0 и миграции Alembic
* Неизменяемая история переходов между этапами — именно она делает возможной
  статистику по воронке
* Фильтрация, полнотекстовый поиск и постраничный вывод
* Docker, Docker Compose и CI, который гоняет тесты против настоящей
  инстанции PostgreSQL
* Структурированное логирование: в каждой строке есть идентификатор запроса,
  и он же возвращается в заголовке `X-Request-ID` и в теле каждой ошибки
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл приложения.

    Здесь происходят две вещи. Устанавливается конфигурация логирования, чтобы
    всё, что пишется при старте, форматировалось так же, как всё, что пишется
    во время запроса. И ничего не делается со схемой — она принадлежит Alembic,
    а не `Base.metadata.create_all`, чтобы история миграций оставалась
    единственным источником правды.
    """
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=DESCRIPTION,
    lifespan=lifespan,
    contact={
        "name": "Мелека Данила",
        "url": "https://github.com/MeldanLess",
    },
    license_info={"name": "MIT"},
    openapi_tags=[
        {"name": "auth", "description": "Регистрация и вход."},
        {"name": "applications", "description": "Отклики на вакансии."},
        {"name": "stats", "description": "Агрегированная статистика по воронке."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Самая внешняя middleware: она назначает идентификатор запроса, который потом
# несут все строки лога и все тела ошибок.
app.add_middleware(RequestContextMiddleware)


# ---------------------------------------------------------------------------
# Роутеры — именно здесь эндпоинты попадают в приложение.
# ---------------------------------------------------------------------------
#
# В FastAPI маршрут не появляется сам оттого, что модуль импортирован:
# импорт нужен, чтобы добраться до объекта `router`, а зарегистрировать его
# должна явная строка `include_router`. Без этих трёх строк приложение
# поднимается «пустым» — на `/` отвечает, а на `/auth/token` возвращает 404.

app.include_router(auth.router)
app.include_router(applications.router)
app.include_router(stats.router)


# ---------------------------------------------------------------------------
# Обработка ошибок — одна форма ответа на весь API.
# ---------------------------------------------------------------------------


def error_body(request: Request, detail, status_code: int, **extra) -> dict:
    """Единая форма ошибки, которую использует весь API.

    `request_id` включён, чтобы пользователь, сообщающий о проблеме, мог назвать
    значение, которое совпадёт со строкой в логе.
    """
    body = {
        "detail": detail,
        "status_code": status_code,
        "path": request.url.path,
        "request_id": get_request_id(),
    }
    body.update(extra)
    return body


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, exc.detail, exc.status_code),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Превращает список ошибок Pydantic в читаемое машинно-ориентированное тело.

    Исходный `errors()` включён, потому что он полезен разработчику клиента, но
    каждая ошибка приведена к сериализуемому виду — так, чтобы объект
    `ValueError` внутри `ctx` не сломал ответ.
    """
    errors = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_body(request, "Ошибка валидации", 422, errors=errors),
    )


@app.get("/", tags=["meta"], summary="Индекс сервиса")
def index():
    """Небольшой индекс, чтобы по корню возвращалось что-то полезное."""
    return {
        "name": settings.app_name,
        "version": settings.version,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/health",
    }
