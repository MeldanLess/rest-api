"""Тесты структурированного логирования и идентификатора запроса.

Намеренно обходятся без базы данных: под проверкой оказываются middleware,
форматтеры и вспомогательные функции, для которых сессия не нужна.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.logging_config import (
    NO_REQUEST_ID,
    REQUEST_ID_HEADER,
    ConsoleFormatter,
    JsonFormatter,
    RequestIdFilter,
    configure_logging,
    get_request_id,
    pseudonymise_email,
)
from app.main import app


@pytest.fixture
def client_without_db():
    """Клиент без подмены базы — хватает для корня и 404."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_log_records():
    """Собирает то, что записал роутер аутентификации.

    Обработчик вешается на собственный логгер роутера, а не используется
    `caplog`: приложение при старте ставит свой корневой обработчик, который
    снял бы захват pytest.
    """
    records: list[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    auth_logger = logging.getLogger("app.routers.auth")
    handler = Collector()
    was_propagating = auth_logger.propagate
    auth_logger.addHandler(handler)
    auth_logger.setLevel(logging.DEBUG)
    auth_logger.propagate = False
    try:
        yield records
    finally:
        auth_logger.removeHandler(handler)
        auth_logger.propagate = was_propagating


def test_kazhdyy_otvet_nosit_identifikator_zaprosa(client_without_db):
    response = client_without_db.get("/")
    assert response.status_code == 200
    request_id = response.headers[REQUEST_ID_HEADER]
    assert request_id
    assert request_id != NO_REQUEST_ID


def test_prislannyy_identifikator_zaprosa_vozvrashchaetsya(client_without_db):
    response = client_without_db.get("/", headers={REQUEST_ID_HEADER: "abc123"})
    assert response.headers[REQUEST_ID_HEADER] == "abc123"


def test_nebezopasnyy_identifikator_zaprosa_zamenyaetsya(client_without_db):
    """Идентификатор, присланный вызывающей стороной, возвращается клиенту,
    поэтому его нужно проверять.

    Значение попадает в заголовок ответа и в строку лога — непроверенное
    значение там — это header injection и возможность подделать запись в логе.
    """
    hostile = "bad id with spaces and <script>"
    response = client_without_db.get("/", headers={REQUEST_ID_HEADER: hostile})
    echoed = response.headers[REQUEST_ID_HEADER]
    assert echoed != hostile
    assert echoed.strip() == echoed
    assert "<" not in echoed and ">" not in echoed


def test_kazhdyy_zapros_poluchaet_svoy_identifikator(client_without_db):
    first = client_without_db.get("/").headers[REQUEST_ID_HEADER]
    second = client_without_db.get("/").headers[REQUEST_ID_HEADER]
    assert first != second


def test_telo_oshibki_nosit_tot_zhe_identifikator(client_without_db):
    response = client_without_db.get("/no-such-path")
    assert response.status_code == 404
    body = response.json()
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert body["status_code"] == 404
    assert body["path"] == "/no-such-path"


def test_vne_zaprosa_identifikatora_net():
    assert get_request_id() == NO_REQUEST_ID


def test_filter_dobavlyaet_identifikator_k_zapisi():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", None, None)
    RequestIdFilter().filter(record)
    assert record.request_id == NO_REQUEST_ID


def test_json_formatter_vydayet_ozhidanye_polya():
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello", None, None)
    record.request_id = "abc123"
    record.event = "test.event"
    record.status_code = 200

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["request_id"] == "abc123"
    assert payload["event"] == "test.event"
    assert payload["status_code"] == 200
    assert "timestamp" in payload


def test_json_formatter_perezhivaet_neserialisuemoe_dopolnitelnoe_pole():
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello", None, None)
    record.request_id = "abc123"
    record.payload = object()

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hello"


def test_console_formatter_dopisyvaet_dopolnitelnye_polya():
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello", None, None)
    record.request_id = "abc123"
    record.event = "test.event"

    line = ConsoleFormatter().format(record)

    assert "hello" in line
    assert "abc123" in line
    assert "event=test.event" in line


def test_nastroyka_logovaniya_ostavlyaet_odin_obrabotchik():
    configure_logging(level="INFO", fmt="json")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)

    configure_logging(level="INFO", fmt="console")
    assert len(logging.getLogger().handlers) == 1
    assert isinstance(logging.getLogger().handlers[0].formatter, ConsoleFormatter)


def test_psevdonym_pochty_stabilen_i_skryvaet_adres():
    digest = pseudonymise_email("Someone@Example.com")

    assert digest == pseudonymise_email("someone@example.com")
    assert digest != pseudonymise_email("someoneelse@example.com")
    assert "someone" not in digest.lower()
    assert len(digest) == 12


def test_uchetnye_dannye_nikogda_ne_popadayut_v_log(
    monkeypatch, client_without_db, auth_log_records
):
    """Неудачный вход не должен писать в лог пароль — и не должен писать адрес."""

    def no_such_user(db, email):
        """Заглушка вместо обращения к базе, чтобы БД не требовалась."""
        return None

    monkeypatch.setattr("app.routers.auth.get_user_by_email", no_such_user)

    response = client_without_db.post(
        "/auth/token",
        data={"username": "nobody@example.com", "password": "supersecret"},
    )
    assert response.status_code == 401

    logged = "\n".join(
        f"{record.getMessage()} {record.__dict__}" for record in auth_log_records
    )
    assert logged, "неудачный вход вообще не был записан"
    assert "supersecret" not in logged
    assert "nobody@example.com" not in logged
