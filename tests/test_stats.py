"""Статистика по воронке откликов."""

import uuid
from datetime import UTC, datetime, timedelta

from app.models import Application, ApplicationEvent, User
from app.security import hash_password

PAYLOAD = {"company": "Яндекс", "role": "Backend", "source": "hh"}


def _create(client, **overrides):
    return client.post("/applications", json={**PAYLOAD, **overrides})


def test_statistika_dlya_pustoy_voronki(auth_client):
    response = auth_client.get("/stats/pipeline")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["active"] == 0
    assert body["terminal"] == 0
    assert body["offer_rate"] == 0.0
    assert body["by_stage"] == []


def test_statistika_schitaet_otkliky_po_etapam(auth_client):
    _create(auth_client, company="А", stage="applied")
    _create(auth_client, company="Б", stage="interview")
    _create(auth_client, company="В", stage="rejected")

    body = auth_client.get("/stats/pipeline").json()

    assert body["total"] == 3
    counts = {item["stage"]: item["count"] for item in body["by_stage"]}
    assert counts == {"applied": 1, "interview": 1, "rejected": 1}


def test_statistika_razdelyaet_aktivnyye_i_finalnyye(auth_client):
    _create(auth_client, company="А", stage="applied")
    _create(auth_client, company="Б", stage="screening")
    _create(auth_client, company="В", stage="offer")
    _create(auth_client, company="Г", stage="rejected")

    body = auth_client.get("/stats/pipeline").json()

    assert body["active"] == 2
    assert body["terminal"] == 2


def test_statistika_schitaet_po_istochnikam(auth_client):
    _create(auth_client, company="А", source="hh")
    _create(auth_client, company="Б", source="hh")
    _create(auth_client, company="В", source="telegram")

    body = auth_client.get("/stats/pipeline").json()

    assert body["by_source"] == {"hh": 2, "telegram": 1}


def test_statistika_schitaet_dolyu_offerov(auth_client):
    _create(auth_client, company="А", stage="offer")
    _create(auth_client, company="Б", stage="rejected")
    _create(auth_client, company="В", stage="applied")
    _create(auth_client, company="Г", stage="applied")

    body = auth_client.get("/stats/pipeline").json()

    assert body["offer_rate"] == 0.25


def test_statistika_ignoruet_chuzhye_otkliky(auth_client, db_session):
    _create(auth_client, company="Моё")

    other = User(
        email="other@example.com", hashed_password=hash_password("password123")
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    db_session.add(Application(owner_id=other.id, company="Их", role="Нет"))
    db_session.commit()

    body = auth_client.get("/stats/pipeline").json()

    assert body["total"] == 1


def test_statistika_soobshchaet_medianu_dney_do_pervogo_otveta(auth_client, db_session):
    created = _create(auth_client).json()

    application = db_session.get(Application, uuid.UUID(created["id"]))
    application.created_at = datetime.now(UTC) - timedelta(days=6)
    db_session.commit()

    event = (
        db_session.query(ApplicationEvent)
        .filter(ApplicationEvent.application_id == application.id)
        .one()
    )
    event.created_at = datetime.now(UTC) - timedelta(days=1)
    db_session.commit()

    body = auth_client.get("/stats/pipeline").json()

    assert body["median_days_to_first_response"] == 5.0


def test_statistika_trebuet_avtorizatsii(client):
    assert client.get("/stats/pipeline").status_code == 401
