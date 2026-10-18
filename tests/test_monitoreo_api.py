"""API del monitoreo (G5): solo ADMIN; Gestión caída → 503 problem+json; dinero como string (F10)."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.application.monitoreo import EjecutarMonitoreo, ListarInformes, MorosoDato, PagoPendienteDato
from app.domain.monitoreo import Parametros
from app.infrastructure.composicion import Monitoreo
from app.infrastructure.keycloak import JwtVerificador
from app.infrastructure.memoria import InformesEnMemoria, MetricasEnMemoria
from app.main import create_app
from tests.conftest import ISSUER, CrearToken, _clave
from tests.test_monitoreo_aplicacion import GestionFalsa, NotificadorFalso, RelojFijo

RUTAS = [("POST", "/monitoreo/ejecutar"), ("GET", "/monitoreo/informes")]


def _cliente(gestion: GestionFalsa) -> TestClient:
    informes = InformesEnMemoria()
    caso = EjecutarMonitoreo(
        gestion, MetricasEnMemoria(), informes, NotificadorFalso(), RelojFijo(), Parametros()
    )
    monitoreo = Monitoreo(caso, ListarInformes(informes))
    return TestClient(create_app(JwtVerificador(ISSUER, lambda _t: _clave.public_key()), monitoreo))


@pytest.fixture()
def cliente() -> TestClient:
    return _cliente(
        GestionFalsa(
            [MorosoDato("U1", Decimal("250.5"), 2), MorosoDato("U2", Decimal("100"), 1)],
            [PagoPendienteDato("P1", Decimal("80"), date(2026, 10, 19))],
        )
    )


def _h(crear_token: CrearToken, *roles: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {crear_token(*roles)}"}


@pytest.mark.parametrize(("metodo", "ruta"), RUTAS)
def test_sin_token_es_401(cliente: TestClient, metodo: str, ruta: str) -> None:
    assert cliente.request(metodo, ruta).status_code == 401


@pytest.mark.parametrize("rol", ["RESIDENTE", "GUARDIA"])
@pytest.mark.parametrize(("metodo", "ruta"), RUTAS)
def test_G5_solo_el_admin_usa_el_monitoreo(
    cliente: TestClient, crear_token: CrearToken, metodo: str, ruta: str, rol: str
) -> None:
    r = cliente.request(metodo, ruta, headers=_h(crear_token, rol))
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")


def test_G5_el_admin_ejecuta_el_agente_y_recibe_el_informe(
    cliente: TestClient, crear_token: CrearToken
) -> None:
    r = cliente.post("/monitoreo/ejecutar", headers=_h(crear_token, "ADMIN"))
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["origen"] == "MANUAL" and cuerpo["lineaBase"] is True and cuerpo["alertas"] == []
    assert cuerpo["metricas"]["unidadesMorosas"] == 2
    assert cuerpo["metricas"]["deudaVencida"] == "350.50"  # F10: string decimal, no número
    assert cuerpo["metricas"]["pagosPendientes"] == 1


def test_G5_los_informes_se_listan_del_mas_reciente_al_mas_antiguo(
    cliente: TestClient, crear_token: CrearToken
) -> None:
    h = _h(crear_token, "ADMIN")
    ids = [cliente.post("/monitoreo/ejecutar", headers=h).json()["id"] for _ in range(3)]
    lista = cliente.get("/monitoreo/informes", headers=h).json()
    assert [i["id"] for i in lista] == list(reversed(ids))
    assert len(cliente.get("/monitoreo/informes?limite=2", headers=h).json()) == 2


@pytest.mark.parametrize("limite", ["0", "51", "x"])
def test_G5_un_limite_invalido_es_400(cliente: TestClient, crear_token: CrearToken, limite: str) -> None:
    assert (
        cliente.get(f"/monitoreo/informes?limite={limite}", headers=_h(crear_token, "ADMIN")).status_code
        == 400
    )


def test_G5_si_gestion_no_responde_es_503_problem_json(crear_token: CrearToken) -> None:
    gestion = GestionFalsa()
    gestion.caida = True
    r = _cliente(gestion).post("/monitoreo/ejecutar", headers=_h(crear_token, "ADMIN"))
    assert r.status_code == 503 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Gestión no disponible"
