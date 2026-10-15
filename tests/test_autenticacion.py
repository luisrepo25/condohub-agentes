from fastapi.testclient import TestClient

from tests.conftest import CrearToken


def _salud(client: TestClient, token: str | None):
    cabeceras = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/salud", headers=cabeceras)


def test_sin_token_responde_401_en_problem_json(client: TestClient) -> None:
    r = _salud(client, None)
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["status"] == 401


def test_token_valido_de_cualquier_rol_ve_la_salud(client: TestClient, crear_token: CrearToken) -> None:
    for rol in ("ADMIN", "RESIDENTE", "GUARDIA"):
        r = _salud(client, crear_token(rol))
        assert r.status_code == 200
        assert r.json() == {"servicio": "agentes", "estado": "OK"}


def test_token_firmado_con_otra_clave_es_401(client: TestClient, crear_token: CrearToken) -> None:
    assert _salud(client, crear_token("ADMIN", firmar_con_clave_ajena=True)).status_code == 401


def test_token_vencido_es_401(client: TestClient, crear_token: CrearToken) -> None:
    assert _salud(client, crear_token("ADMIN", expira_en=-60)).status_code == 401


def test_token_de_otro_emisor_es_401(client: TestClient, crear_token: CrearToken) -> None:
    assert _salud(client, crear_token("ADMIN", issuer="http://otro-realm/realms/x")).status_code == 401


def test_basura_como_token_es_401(client: TestClient) -> None:
    assert _salud(client, "esto.no.es-un-jwt").status_code == 401


def test_roles_que_no_son_de_condohub_se_ignoran(client: TestClient, crear_token: CrearToken) -> None:
    # offline_access viene en todo token de Keycloak; sin roles de CondoHub no se puede usar nada
    r = client.post(
        "/misiones",
        headers={"Authorization": f"Bearer {crear_token('superusuario')}"},
        json={"objetivo": "x"},
    )
    assert r.status_code == 403
