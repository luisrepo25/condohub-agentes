"""Matriz rol × endpoint. Permitido ⇒ llega a la lógica (hoy 501); no permitido ⇒ 403; sin token ⇒ 401.

Misiones y confirmaciones son solo para ADMIN (G1, G2): residente y guardia no lanzan agentes.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CrearToken

UUID_X = "11111111-1111-4111-8111-111111111111"


@dataclass(frozen=True)
class Endpoint:
    nombre: str
    metodo: str
    ruta: str
    kwargs: dict[str, Any] = field(default_factory=dict)


ENDPOINTS = [
    Endpoint(
        "G1_lanzar_mision", "POST", "/misiones", {"json": {"objetivo": "Gestiona la morosidad del mes"}}
    ),
    Endpoint("G3_obtener_mision", "GET", f"/misiones/{UUID_X}"),
    Endpoint("G2_aprobar_accion", "POST", f"/confirmaciones/{UUID_X}/aprobar"),
    Endpoint("G2_rechazar_accion", "POST", f"/confirmaciones/{UUID_X}/rechazar"),
]
ROLES = ("ADMIN", "RESIDENTE", "GUARDIA")


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.nombre)
def test_sin_token_es_401(client: TestClient, endpoint: Endpoint) -> None:
    assert client.request(endpoint.metodo, endpoint.ruta, **endpoint.kwargs).status_code == 401


@pytest.mark.parametrize("rol", ROLES)
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.nombre)
def test_solo_el_admin_usa_los_agentes(
    client: TestClient, crear_token: CrearToken, endpoint: Endpoint, rol: str
) -> None:
    r = client.request(
        endpoint.metodo,
        endpoint.ruta,
        headers={"Authorization": f"Bearer {crear_token(rol)}"},
        **endpoint.kwargs,
    )
    assert r.status_code == (501 if rol == "ADMIN" else 403), f"{rol} en {endpoint.nombre}"
    assert r.headers["content-type"].startswith("application/problem+json")


def test_los_501_se_identifican_como_no_implementado(client: TestClient, crear_token: CrearToken) -> None:
    r = client.get(f"/misiones/{UUID_X}", headers={"Authorization": f"Bearer {crear_token('ADMIN')}"})
    assert r.json()["code"] == "NO_IMPLEMENTADO"


def test_solicitud_mal_formada_es_400_para_el_admin(client: TestClient, crear_token: CrearToken) -> None:
    r = client.post("/misiones", headers={"Authorization": f"Bearer {crear_token('ADMIN')}"}, json={})
    assert r.status_code == 400
