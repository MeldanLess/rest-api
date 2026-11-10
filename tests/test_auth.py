"""Регистрация, вход и авторизованный пользователь."""

from app.models import User


def test_registratsiya_sozdayet_polzovatelya(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "new@example.com",
            "password": "strongpassword",
            "full_name": "Новый человек",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["full_name"] == "Новый человек"
    assert "password" not in body
    assert "hashed_password" not in body


def test_registratsiya_privodit_pochtu_k_nizhnemu_registru(client):
    response = client.post(
        "/auth/register", json={"email": "MiXeD@Example.com", "password": "strongpassword"}
    )

    assert response.status_code == 201
    assert response.json()["email"] == "mixed@example.com"


def test_registratsiya_otklanyaet_dublikat_pochty(client, user):
    response = client.post(
        "/auth/register", json={"email": user.email, "password": "strongpassword"}
    )

    assert response.status_code == 409
    assert "уже есть" in response.json()["detail"]


def test_registratsiya_otklanyaet_korotkiy_parol(client):
    response = client.post(
        "/auth/register", json={"email": "short@example.com", "password": "abc"}
    )

    assert response.status_code == 422


def test_registratsiya_otklanyaet_nemailnuyu_pochtu(client):
    response = client.post(
        "/auth/register", json={"email": "not-an-email", "password": "strongpassword"}
    )

    assert response.status_code == 422


def test_parol_hranitsya_kak_hesh_a_ne_kak_otkrytyy_text(client, db_session):
    client.post(
        "/auth/register", json={"email": "hashed@example.com", "password": "plaintextsecret"}
    )

    stored = db_session.query(User).filter(User.email == "hashed@example.com").one()
    assert stored.hashed_password != "plaintextsecret"
    assert stored.hashed_password.startswith("$2")


def test_vhod_vozvrashchaet_token_i_polzovatelya(client, user):
    response = client.post(
        "/auth/token", data={"username": user.email, "password": "password123"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == user.email


def test_vhod_ne_zavisit_ot_registra_pochty(client, user):
    response = client.post(
        "/auth/token", data={"username": user.email.upper(), "password": "password123"}
    )

    assert response.status_code == 200


def test_vhod_s_nevernym_parolem_otklonyaetsya(client, user):
    response = client.post(
        "/auth/token", data={"username": user.email, "password": "wrongpassword"}
    )

    assert response.status_code == 401


def test_vhod_s_neizvestnoy_pochtoy_daet_takoe_zhe_soobshchenie(client, user):
    unknown = client.post(
        "/auth/token", data={"username": "nobody@example.com", "password": "password123"}
    )
    wrong_password = client.post(
        "/auth/token", data={"username": user.email, "password": "wrongpassword"}
    )

    # Одинаковые ответы, чтобы по эндпоинту нельзя было выяснить, какие
    # адреса почты зарегистрированы.
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json()["detail"] == wrong_password.json()["detail"]


def test_me_vozvrashchaet_tekushchego_polzovatelya(client, user, token):
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_me_bez_tokena_otklonyaetsya(client):
    assert client.get("/auth/me").status_code == 401


def test_me_s_ekrannym_tokenom_otklonyaetsya(client):
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401


def test_me_s_poddelnannym_tokenom_otklonyaetsya(client, user, token):
    # Меняем последний символ подписи.
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"})

    assert response.status_code == 401
