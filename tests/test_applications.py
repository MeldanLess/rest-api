"""Ресурс откликов: CRUD, фильтрация, постраничный вывод и смена этапов."""

import pytest

from app.models import Application, User
from app.security import hash_password

PAYLOAD = {
    "company": "Яндекс",
    "role": "Junior Python-разработчик",
    "location": "Москва",
    "source": "hh",
    "priority": "high",
    "salary_min": 120000,
    "salary_max": 160000,
    "notes": "Отклик через hh.ru",
}


def _create(client, **overrides):
    payload = {**PAYLOAD, **overrides}
    return client.post("/applications", json=payload)


# ---------------------------------------------------------------------------
# Создание
# ---------------------------------------------------------------------------


def test_sozdanie_vozvrashchaet_201_i_sam_otklik(auth_client):
    response = _create(auth_client)

    assert response.status_code == 201
    body = response.json()
    assert body["company"] == "Яндекс"
    assert body["stage"] == "applied"
    assert body["currency"] == "RUB"
    assert body["id"]


def test_sozdanie_prinimaet_yavno_zadannyy_etap(auth_client):
    response = _create(auth_client, stage="interview")

    assert response.status_code == 201
    assert response.json()["stage"] == "interview"


def test_sozdanie_otklanyaet_putostoy_kompaniyu(auth_client):
    response = _create(auth_client, company="")

    assert response.status_code == 422


def test_sozdanie_otklanyaet_neizvestnyy_etap(auth_client):
    response = _create(auth_client, stage="teleported")

    assert response.status_code == 422


def test_sozdanie_trebuet_avtorizatsii(client):
    assert client.post("/applications", json=PAYLOAD).status_code == 401


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------


def test_chtenie_vozvrashchaet_otklik(auth_client):
    created = _create(auth_client).json()

    response = auth_client.get(f"/applications/{created['id']}")

    assert response.status_code == 200
    assert response.json()["company"] == "Яндекс"


def test_chtenie_vozvrashchaet_404_dlya_neizvestnogo_id(auth_client):
    response = auth_client.get("/applications/2f1b0c2a-0000-4000-8000-000000000000")

    assert response.status_code == 404


def test_chtenie_chuzhogo_otklika_daet_404(auth_client, db_session):
    other = User(
        email="other@example.com", hashed_password=hash_password("password123")
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    theirs = Application(owner_id=other.id, company="Тайная компания", role="Скрытая")
    db_session.add(theirs)
    db_session.commit()
    db_session.refresh(theirs)

    response = auth_client.get(f"/applications/{theirs.id}")

    # 404, а не 403: 403 подтверждал бы, что такой id существует.
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Список
# ---------------------------------------------------------------------------


def test_v_spiske_tolko_otkliky_zakazatelya(auth_client, db_session):
    _create(auth_client, company="Моё")

    other = User(
        email="other@example.com", hashed_password=hash_password("password123")
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    db_session.add(
        Application(owner_id=other.id, company="Их", role="Не моё")
    )
    db_session.commit()

    response = auth_client.get("/applications")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["company"] == "Моё"


def test_v_spiske_filtr_po_etapu(auth_client):
    _create(auth_client, company="А")
    _create(auth_client, company="Б", stage="interview")

    response = auth_client.get("/applications", params={"stage": "interview"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["company"] == "Б"


def test_v_spiske_filtr_po_istochniku(auth_client):
    _create(auth_client, company="А", source="hh")
    _create(auth_client, company="Б", source="telegram")

    response = auth_client.get("/applications", params={"source": "telegram"})

    assert response.json()["total"] == 1
    assert response.json()["items"][0]["company"] == "Б"


def test_v_spiske_iset_po_kompanii_i_dolzhnosti(auth_client):
    _create(auth_client, company="Яндекс", role="Backend")
    _create(auth_client, company="Avito", role="Frontend")

    # Ищем часть, написанную строчными, чтобы результат не зависел от
    # локали collation в базе.
    response = auth_client.get("/applications", params={"q": "декс"})

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["company"] == "Яндекс"


def test_poisk_ne_zavisit_ot_registra(auth_client):
    _create(auth_client, company="Avito", role="Backend")

    response = auth_client.get("/applications", params={"q": "AVITO"})

    assert response.json()["total"] == 1


def test_v_spiske_only_active_isklyuchaet_finalnyye_etapy(auth_client):
    _create(auth_client, company="Активный")
    _create(auth_client, company="Завершённый", stage="rejected")

    response = auth_client.get("/applications", params={"active_only": True})

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["company"] == "Активный"


def test_v_spiske_postranichno_vydelyaetsya(auth_client):
    for index in range(5):
        _create(auth_client, company=f"Компания {index}")

    first = auth_client.get("/applications", params={"limit": 2, "offset": 0}).json()
    second = auth_client.get("/applications", params={"limit": 2, "offset": 2}).json()

    assert first["total"] == 5
    assert len(first["items"]) == 2
    assert len(second["items"]) == 2
    # Страницы не должны пересекаться.
    assert {item["id"] for item in first["items"]}.isdisjoint(
        {item["id"] for item in second["items"]}
    )


def test_v_spiske_otklanyaet_slishkom_bolshoy_limit(auth_client):
    response = auth_client.get("/applications", params={"limit": 5000})

    assert response.status_code == 422


def test_v_spiske_otklanyaet_neizvestnyy_filtr_po_etapu(auth_client):
    response = auth_client.get("/applications", params={"stage": "nonsense"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Обновление и удаление
# ---------------------------------------------------------------------------


def test_patch_menyaet_tolko_prislannye_polya(auth_client):
    created = _create(auth_client).json()

    response = auth_client.patch(
        f"/applications/{created['id']}", json={"priority": "low"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["priority"] == "low"
    assert body["company"] == "Яндекс"  # не тронуто
    assert body["role"] == "Junior Python-разработчик"  # не тронуто


def test_patch_otklanyaet_neizvestnoe_pole(auth_client):
    created = _create(auth_client).json()

    response = auth_client.patch(
        f"/applications/{created['id']}", json={"not_a_field": "value"}
    )

    assert response.status_code == 422


def test_udalenie_ubiraet_otklik(auth_client):
    created = _create(auth_client).json()

    deleted = auth_client.delete(f"/applications/{created['id']}")
    fetched = auth_client.get(f"/applications/{created['id']}")

    assert deleted.status_code == 204
    assert fetched.status_code == 404


def test_udalenie_chuzhogo_otklika_daet_404(auth_client, db_session):
    other = User(
        email="other@example.com", hashed_password=hash_password("password123")
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    theirs = Application(owner_id=other.id, company="Их", role="Не моё")
    db_session.add(theirs)
    db_session.commit()
    db_session.refresh(theirs)

    response = auth_client.delete(f"/applications/{theirs.id}")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Переходы между этапами и история
# ---------------------------------------------------------------------------


def test_smena_etapa_menyaet_etap(auth_client):
    created = _create(auth_client).json()

    response = auth_client.post(
        f"/applications/{created['id']}/stage", json={"to_stage": "screening"}
    )

    assert response.status_code == 200
    assert response.json()["stage"] == "screening"


def test_smena_etapa_popadaet_v_istoriyu(auth_client):
    created = _create(auth_client).json()

    auth_client.post(
        f"/applications/{created['id']}/stage",
        json={"to_stage": "screening", "note": "Позвонил рекрутер"},
    )

    events = auth_client.get(f"/applications/{created['id']}/events").json()

    assert len(events) == 2
    assert events[0]["to_stage"] == "applied"
    assert events[0]["from_stage"] is None
    assert events[1]["from_stage"] == "applied"
    assert events[1]["to_stage"] == "screening"
    assert events[1]["note"] == "Позвонил рекрутер"


def test_smena_na_nerealnyy_etap_otklonyaetsya(auth_client):
    created = _create(auth_client).json()

    # applied -> offer пропускает скрининг и собеседование, что запрещено.
    response = auth_client.post(
        f"/applications/{created['id']}/stage", json={"to_stage": "offer"}
    )

    assert response.status_code == 409
    assert "Невозможно перевести" in response.json()["detail"]


def test_smena_na_tot_zhe_etap_razreshena(auth_client):
    created = _create(auth_client).json()

    response = auth_client.post(
        f"/applications/{created['id']}/stage", json={"to_stage": "applied"}
    )

    assert response.status_code == 200


def test_smena_etapa_vidna_v_spiske(auth_client):
    created = _create(auth_client).json()
    auth_client.post(f"/applications/{created['id']}/stage", json={"to_stage": "screening"})

    response = auth_client.get("/applications", params={"stage": "screening"})

    assert response.json()["total"] == 1


@pytest.mark.parametrize(
    "stage", ["applied", "screening", "interview", "offer", "rejected", "withdrawn"]
)
def test_lyuboy_etap_prinimaetsya_filtrom(auth_client, stage):
    _create(auth_client, stage=stage)

    response = auth_client.get("/applications", params={"stage": stage})

    assert response.status_code == 200
    assert response.json()["total"] == 1
