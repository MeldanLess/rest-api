"""Индекс сервиса, проверка состояния и сгенерированная схема OpenAPI."""


def test_indeks_ukazyvaet_na_dokumentatsiyu(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["docs"] == "/docs"
    assert body["openapi"] == "/openapi.json"
    assert body["health"] == "/health"


def test_proverka_sostoyaniya_soobshchaet_chto_baza_dostupna(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"


def test_proverka_sostoyaniya_ne_trebuet_avtorizatsii(client):
    # У системы мониторинга нет учётных данных.
    assert client.get("/health").status_code == 200


def test_shema_openapi_generiruyetsya(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "ApplyTrack API"

    paths = schema["paths"]
    for path in (
        "/auth/register",
        "/auth/token",
        "/auth/me",
        "/applications",
        "/applications/{application_id}",
        "/applications/{application_id}/stage",
        "/applications/{application_id}/events",
        "/stats/pipeline",
        "/health",
    ):
        assert path in paths, f"{path} missing from the OpenAPI schema"


def test_stranitsa_dokumentatsii_otdaetsya(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_neizvestnyy_marshrut_daet_strukturirovannyy_404(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert body["path"] == "/does-not-exist"
