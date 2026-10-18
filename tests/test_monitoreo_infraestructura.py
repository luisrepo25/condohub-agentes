"""Adaptadores del monitoreo con transportes simulados de httpx: sin red ni servicios reales."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.application.monitoreo import GestionNoDisponible, NotificacionFallida
from app.config_monitoreo import ConfigMonitoreo
from app.domain.monitoreo import Informe, Metricas, Origen
from app.infrastructure.gestion_graphql import GestionGraphQL
from app.infrastructure.notificador_webhook import NotificadorWebhook
from app.infrastructure.token_servicio import TokenServicio


def _gestion(respuesta: httpx.Response, capturas: list[httpx.Request] | None = None) -> GestionGraphQL:
    def manejador(peticion: httpx.Request) -> httpx.Response:
        if capturas is not None:
            capturas.append(peticion)
        return respuesta

    return GestionGraphQL(
        "http://gestion/graphql", lambda: "tok", httpx.Client(transport=httpx.MockTransport(manejador))
    )


def test_G5_gestion_morosos_se_lee_con_una_query_y_el_token_de_servicio() -> None:
    capturas: list[httpx.Request] = []
    datos = {"data": {"morosos": [{"unidadId": "u1", "deudaVencida": "390.00", "expensasVencidas": 2}]}}
    morosos = _gestion(httpx.Response(200, json=datos), capturas).morosos()
    assert morosos[0].deuda_vencida == Decimal("390.00") and morosos[0].expensas_vencidas == 2
    assert capturas[0].headers["Authorization"] == "Bearer tok"
    consulta = json.loads(capturas[0].content)["query"]
    assert consulta.lstrip().startswith("{") and "mutation" not in consulta  # G2: solo lectura


def test_F8_gestion_pagos_pendientes_se_leen_con_su_fecha() -> None:
    datos = {"data": {"pagosPendientes": [{"id": "p1", "monto": "80.00", "fechaPago": "2026-10-19"}]}}
    pagos = _gestion(httpx.Response(200, json=datos)).pagos_pendientes()
    assert pagos[0].fecha_pago == date(2026, 10, 19) and pagos[0].monto == Decimal("80.00")


@pytest.mark.parametrize(
    "respuesta",
    [
        httpx.Response(401),
        httpx.Response(500),
        httpx.Response(200, text="no es json"),
        httpx.Response(200, json={"errors": [{"message": "FORBIDDEN"}]}),
        httpx.Response(200, json={"data": None}),
        httpx.Response(200, json={"data": {"morosos": [{"unidadId": "u1"}]}}),
        httpx.Response(
            200,
            json={"data": {"morosos": [{"unidadId": "u1", "deudaVencida": "abc", "expensasVencidas": 1}]}},
        ),
    ],
)
def test_G5_cualquier_falla_de_gestion_es_gestion_no_disponible(respuesta: httpx.Response) -> None:
    with pytest.raises(GestionNoDisponible):
        _gestion(respuesta).morosos()


def test_G5_gestion_sin_conexion_es_gestion_no_disponible() -> None:
    def cae(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    gestion = GestionGraphQL(
        "http://gestion/graphql", lambda: "t", httpx.Client(transport=httpx.MockTransport(cae))
    )
    with pytest.raises(GestionNoDisponible):
        gestion.pagos_pendientes()


def _token(respuesta: httpx.Response, reloj: list[float], llamadas: list[httpx.Request]) -> TokenServicio:
    def manejador(peticion: httpx.Request) -> httpx.Response:
        llamadas.append(peticion)
        return respuesta

    return TokenServicio(
        "http://kc/token",
        "condohub-servicios",
        "secreto",
        httpx.Client(transport=httpx.MockTransport(manejador)),
        lambda: reloj[0],
    )


def test_G5_el_token_de_servicio_se_guarda_y_se_renueva_al_vencer() -> None:
    reloj, llamadas = [0.0], []
    token = _token(httpx.Response(200, json={"access_token": "abc", "expires_in": 300}), reloj, llamadas)
    assert token() == "abc" and token() == "abc" and len(llamadas) == 1
    assert b"grant_type=client_credentials" in llamadas[0].content
    reloj[0] = 271.0  # 300 s − 30 s de margen
    token()
    assert len(llamadas) == 2


def test_G5_keycloak_rechaza_la_cuenta_de_servicio() -> None:
    with pytest.raises(GestionNoDisponible):
        _token(httpx.Response(401), [0.0], [])()


def test_G5_sin_secreto_no_se_intenta_pedir_el_token() -> None:
    token = TokenServicio(
        "http://kc/token",
        "condohub-servicios",
        "",
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
    )
    with pytest.raises(GestionNoDisponible):
        token()


def _informe() -> Informe:
    ahora = datetime(2026, 10, 20, tzinfo=UTC)
    return Informe.nuevo(ahora, Origen.MANUAL, Metricas(ahora, 1, Decimal("1.00"), 0), (), "resumen", False)


def test_G5_el_aviso_a_n8n_lleva_el_resumen_y_las_alertas() -> None:
    cuerpos: list[Any] = []

    def manejador(p: httpx.Request) -> httpx.Response:
        cuerpos.append(json.loads(p.content))
        return httpx.Response(200)

    NotificadorWebhook(
        "http://n8n/webhook/alertas", httpx.Client(transport=httpx.MockTransport(manejador))
    ).avisar(_informe())
    assert cuerpos[0]["resumen"] == "resumen" and cuerpos[0]["alertas"] == []


@pytest.mark.parametrize("respuesta", [httpx.Response(500), httpx.Response(404)])
def test_G5_si_n8n_responde_error_la_notificacion_falla(respuesta: httpx.Response) -> None:
    with pytest.raises(NotificacionFallida):
        NotificadorWebhook(
            "http://n8n/x", httpx.Client(transport=httpx.MockTransport(lambda r: respuesta))
        ).avisar(_informe())


def test_G5_los_umbrales_salen_de_las_variables_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOREO_AUMENTO_MOROSIDAD", "0.35")
    monkeypatch.setenv("MONITOREO_PAGOS_PENDIENTES_MAX", "9")
    monkeypatch.setenv("CONDOHUB_SERVICIOS_SECRET", "s3")
    config = ConfigMonitoreo.desde_entorno()
    assert (
        config.parametros.aumento_morosidad == Decimal("0.35") and config.parametros.pagos_pendientes_max == 9
    )
    assert config.servicios_client_secret == "s3" and config.persistencia == "memoria"
