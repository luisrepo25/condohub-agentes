import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.application.herramientas import AccionNoDisponible
from app.infrastructure.recargos_gestion import RecargosGestion


def _recargos(manejador: Any) -> RecargosGestion:
    cliente = httpx.Client(transport=httpx.MockTransport(manejador))
    return RecargosGestion("http://gestion/graphql", lambda: "token-servicio", cliente)


def test_F5_proponer_recargo_llama_a_la_mutation_de_gestion_con_el_monto_aprobado() -> None:
    recibidas: list[httpx.Request] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        recibidas.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "proponerRecargo": [
                        {"id": "p1", "cargoOrigenId": "c1", "periodo": "2026-10", "monto": "7.80",
                         "estado": "PROPUESTO"},
                        {"id": "p2", "cargoOrigenId": "c2", "periodo": "2026-10", "monto": "3.00",
                         "estado": "PROPUESTO"},
                    ]
                }
            },
        )

    resultado = _recargos(manejador).proponer("u1", Decimal("10.8"), "Mora de 1 mes")

    assert resultado["propuestaIds"] == ["p1", "p2"]
    assert resultado["monto"] == "10.80"
    assert resultado["estado"] == "PROPUESTO"
    cuerpo = json.loads(recibidas[0].content)
    assert "proponerRecargo" in cuerpo["query"]
    assert cuerpo["query"].startswith("mutation")
    assert cuerpo["variables"] == {"unidadId": "u1", "monto": "10.80", "motivo": "Mora de 1 mes"}
    assert recibidas[0].headers["Authorization"] == "Bearer token-servicio"


def test_F5_si_gestion_rechaza_el_monto_la_accion_falla_con_el_codigo() -> None:
    def manejador(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errors": [
                    {"message": "El recargo del mes es 7.80; se pidió 50.00", "extensions": {"code": "F5"}}
                ],
                "data": None,
            },
        )

    with pytest.raises(AccionNoDisponible, match=r"\(F5\).*7\.80"):
        _recargos(manejador).proponer("u1", Decimal("50"), "x")


def test_si_gestion_no_responde_la_accion_falla_sin_simular_el_recargo() -> None:
    def cae(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=request)

    with pytest.raises(AccionNoDisponible, match="no se registró"):
        _recargos(cae).proponer("u1", Decimal("7.80"), "x")


def test_un_error_http_de_gestion_hace_fallar_la_accion() -> None:
    with pytest.raises(AccionNoDisponible, match="HTTP 503"):
        _recargos(lambda request: httpx.Response(503)).proponer("u1", Decimal("7.80"), "x")
