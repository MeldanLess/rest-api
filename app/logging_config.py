"""Структурированное логирование с идентификатором запроса.

API должен отвечать на два вопроса, на которые обычный access-лог не отвечает:

* *К какому запросу относится эта строка?* — в каждой строке лога есть
  **идентификатор запроса**, поэтому строки одного запроса можно вытащить из
  лога целиком.
* *Что ещё происходило с этим запросом?* — идентификатор возвращается клиенту
  в заголовке `X-Request-ID` и в теле каждой ошибки, поэтому пользователь может
  назвать его в баг-репорте, и его можно сопоставить с записью в логе.

Поддерживаются два формата вывода:

``console``
    Читаемый вид для локальной разработки::

        2026-11-09 14:22:31 INFO    [9f2c1a8e4b7d] app.routers.auth: вход выполнен user_id=…

``json``
    Один JSON-объект на строку — для production. Именно это умеет индексировать
    сборщик логов: поля адресуемы, а не спрятаны в строке, которую надо парсить.

Формат выбирается настройкой ``LOG_FORMAT``. В production по умолчанию
используется JSON, если не сказано иное — см.
``Settings._json_logs_in_production``.

**Учётные данные в лог никогда не попадают.** Неудачный вход записывается с
*псевдонимом* адреса почты (усечённый SHA-256), которого хватает, чтобы
сопоставить повторные попытки, не записывая адрес в файл, который прочитает
много людей.
"""

import hashlib
import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Идентификатор текущего обрабатываемого запроса.
#:
#: Именно :class:`~contextvars.ContextVar`, а не thread-local: запрос может
#: обрабатываться в потоке из пула (FastAPI выполняет sync-эндпоинты именно
#: так), и thread-local там был бы не виден.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

#: Заголовок, которым идентификатор запроса заходит в сервис и выходит из него.
REQUEST_ID_HEADER = "X-Request-ID"

#: Значение, когда запроса нет.
NO_REQUEST_ID = "-"

#: Идентификатор запроса может содержать только эти символы. Всё остальное
#: заменяется сгенерированным: значение возвращается в заголовке ответа и
#: попадает в строку лога, а непроверенное значение там — это и header
#: injection, и возможность подделать запись в логе.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Атрибуты, которые есть у любого `LogRecord`. Всё остальное на записи
#: пришло через `extra=` и является полем, которое стоит показать.
_RESERVED_RECORD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName", "request_id"}

logger = logging.getLogger("app")


def get_request_id() -> str:
    """Идентификатор текущего запроса или ``"-"`` вне запроса."""
    return request_id_var.get() or NO_REQUEST_ID


def pseudonymise_email(email: str) -> str:
    """Устойчивый необратимый идентификатор адреса почты.

    Один и тот же адрес всегда даёт один и тот же дайджест, поэтому повторные
    неудачные попытки входа можно сопоставить, но сам адрес в лог не попадает.

    >>> pseudonymise_email("Someone@Example.com") == pseudonymise_email(
    ...     "someone@example.com"
    ... )
    True
    """
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:12]


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Поля, прикреплённые к записи через `extra=`."""
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RESERVED_RECORD_ATTRS
    }


class RequestIdFilter(logging.Filter):
    """Добавляет текущий идентификатор запроса к каждой прошедшей записи."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """Один JSON-объект на строку — формат, который умеет индексировать сборщик."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", NO_REQUEST_ID),
        }
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Читаемая строка для терминала, к которой дописаны дополнительные поля."""

    default_time_format = "%Y-%m-%d %H:%M:%S"

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)-7s [%(request_id)-12s] %(name)s: %(message)s"
        )

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = _extra_fields(record)
        if extras:
            line += " " + " ".join(f"{key}={value}" for key, value in extras.items())
        return line


def configure_logging(*, level: str = "INFO", fmt: str = "console") -> None:
    """Устанавливает конфигурацию логирования для всего приложения.

    Собственный access-лог uvicorn выключается: middleware из этого модуля
    уже пишет по одной, более полной строке на запрос, а два access-лога на
    один запрос — это на один лог больше. Ошибки uvicorn остаются: там видно
    неудачный старт.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Access-лог uvicorn дублировал бы строку middleware.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # Сторонние логгеры, полезные при отладке и лишние в файле лога: HTTP-клиент
    # пишет каждый запрос, а SQLAlchemy — каждый оператор, когда включён echo.
    for name in ("httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _request_id_from_scope(scope: Scope) -> str:
    """Идентификатор, который используется для этого запроса.

    Идентификатор, присланный вызывающей стороной, уважается — именно так
    запрос остаётся прослеживаемым через границу сервисов, — но только если он
    выглядит безопасным. Всё остальное заменяется сгенерированным, а не
    возвращается как есть.
    """
    for raw_key, raw_value in scope.get("headers", []):
        if raw_key.lower() == REQUEST_ID_HEADER.lower().encode("latin-1"):
            candidate = raw_value.decode("latin-1", errors="ignore").strip()
            if _SAFE_REQUEST_ID.match(candidate):
                return candidate
            break
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Назначает идентификатор запроса, измеряет время и пишет итог.

    Написано как чистый ASGI, а не через ``BaseHTTPMiddleware`` намеренно:
    ``BaseHTTPMiddleware`` оборачивает ответ в новый ``StreamingResponse``, что
    ломает фоновые задачи и меняет способ потоковой передачи ответа. Middleware
    достаточно маленький, чтобы не платить за эту цену.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from_scope(scope)
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (
                        REQUEST_ID_HEADER.lower().encode("latin-1"),
                        request_id.encode("latin-1"),
                    ),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "Необработанная ошибка при обработке запроса",
                extra={
                    "event": "request.error",
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                },
            )
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            # Пишем до сброса переменной контекста: фильтр берёт идентификатор
            # именно из неё, и эта строка должна нести тот же идентификатор, что
            # и остальные строки запроса.
            logger.info(
                "запрос завершён",
                extra={
                    "event": "request.completed",
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            request_id_var.reset(token)
