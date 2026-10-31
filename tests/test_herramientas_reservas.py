"""Herramientas de Reservas del agente (solo lectura) y el reporte consolidado (E6, C2).

Gestión y Reservas tienen cada una su base de datos: no hay JOIN entre ellas. El agente llama a cada API
con su contrato y combina las respuestas; cada contexto conserva sus datos.
"""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.application.herramientas import AccionNoDisponible
from app.application.herramientas_reservas import HERRAMIENTAS_RESERVAS, CatalogoConReservas, ReservaDato
from app.domain.mision import Riesgo
from app.infrastructure.reservas_http import ReservasHttp
from tests.dobles_mision import Mundo


def _reserva(id_: str, estado: str, inicio: str, unidad: str = "u1") -> ReservaDato:
    return ReservaDato(
        id_,
        "area-1",
        unidad,
        inicio,
        inicio.replace("14", "18"),
        estado,
        Decimal("500.00"),
        Decimal("300.00"),
        2,
    )


class ReservasFalsas:
    def __init__(self, reservas: list[ReservaDato] | None = None, falla: bool = False) -> None:
        self.reservas = reservas or []
        self.falla = falla
        self.pedidos: list[tuple[str | None, str | None]] = []

    def reservas_de(self, unidad_id: str | None, estado: str | None) -> list[ReservaDato]:
        self.pedidos.append((unidad_id, estado))
        if self.falla:
            raise AccionNoDisponible("Reservas no responde")
        return [
            r
            for r in self.reservas
            if (unidad_id is None or r.unidad_id == unidad_id) and (estado is None or r.estado == estado)
        ]


def _catalogo(reservas: ReservasFalsas) -> CatalogoConReservas:
    return CatalogoConReservas(Mundo().catalogo, reservas)


class TestCatalogo:
    def test_E6_suma_dos_herramientas_de_lectura_a_las_existentes(self) -> None:
        catalogo = _catalogo(ReservasFalsas())

        nombres = [h.nombre for h in catalogo.listar()]

        assert nombres[:6] == [
            "consultar_morosos",
            "estado_de_cuenta",
            "pagos_pendientes",
            "calcular_recargo",
            "proponer_recargo",
            "enviar_recordatorio",
        ]
        assert nombres[6:] == ["consultar_reservas", "resumen_de_unidad"]
        assert all(h.riesgo is Riesgo.LECTURA for h in HERRAMIENTAS_RESERVAS)  # G2: ninguna escribe

    def test_las_herramientas_de_Gestion_se_siguen_resolviendo_por_el_catalogo_base(self) -> None:
        r = _catalogo(ReservasFalsas()).ejecutar("pagos_pendientes", {})

        assert r["total"] == 1

    def test_una_herramienta_desconocida_sigue_siendo_un_error(self) -> None:
        with pytest.raises(ValueError):
            _catalogo(ReservasFalsas()).ejecutar("borrar_todo", {})


class TestConsultarReservas:
    def test_lista_las_reservas_de_una_unidad_filtrando_por_estado(self) -> None:
        falsas = ReservasFalsas(
            [
                _reserva("r1", "CONFIRMADA", "2026-11-20T14:00:00Z"),
                _reserva("r2", "CANCELADA", "2026-11-22T14:00:00Z"),
                _reserva("r3", "CONFIRMADA", "2026-11-25T14:00:00Z", unidad="u2"),
            ]
        )

        r = _catalogo(falsas).ejecutar("consultar_reservas", {"unidadId": "u1", "estado": "CONFIRMADA"})

        assert r["total"] == 1
        assert r["reservas"][0] == {
            "id": "r1",
            "areaId": "area-1",
            "inicio": "2026-11-20T14:00:00Z",
            "fin": "2026-11-20T18:00:00Z",
            "estado": "CONFIRMADA",
            "costoUso": "500.00",
            "garantia": "300.00",
            "invitados": 2,
        }
        assert falsas.pedidos == [("u1", "CONFIRMADA")]

    def test_un_estado_que_no_existe_se_rechaza_antes_de_llamar_a_Reservas(self) -> None:
        falsas = ReservasFalsas()

        with pytest.raises(ValueError, match="estado"):
            _catalogo(falsas).validar("consultar_reservas", {"estado": "BORRADA"})

        assert falsas.pedidos == []


class TestResumenDeUnidad:
    def test_C2_combina_las_finanzas_de_Gestion_con_las_reservas_de_Reservas_sin_JOIN(self) -> None:
        falsas = ReservasFalsas(
            [
                _reserva("r1", "CONFIRMADA", "2026-11-20T14:00:00Z"),
                _reserva("r2", "SOLICITADA", "2026-11-18T14:00:00Z"),
                _reserva("r3", "CANCELADA", "2026-11-10T14:00:00Z"),
                _reserva("r4", "FINALIZADA", "2026-10-01T14:00:00Z"),
            ]
        )

        r = _catalogo(falsas).ejecutar("resumen_de_unidad", {"unidadId": "u1"})

        assert r["finanzas"]["codigo"] == "B-101" and r["finanzas"]["deudaVencida"] == "390.00"  # de Gestión
        assert r["reservas"]["total"] == 4  # de Reservas
        assert r["reservas"]["activas"] == 2
        assert [p["id"] for p in r["reservas"]["proximas"]] == [
            "r2",
            "r1",
        ]  # las activas, la más cercana primero
        assert "sin JOIN" in r["nota"]
        assert falsas.pedidos == [("u1", None)]  # Reservas se consulta por su API

    def test_una_unidad_sin_reservas_devuelve_ceros_y_no_falla(self) -> None:
        r = _catalogo(ReservasFalsas()).ejecutar("resumen_de_unidad", {"unidadId": "u1"})

        assert r["reservas"] == {"total": 0, "activas": 0, "proximas": []}

    def test_si_Reservas_no_responde_el_error_llega_al_agente_con_su_motivo(self) -> None:
        with pytest.raises(AccionNoDisponible, match="Reservas"):
            _catalogo(ReservasFalsas(falla=True)).ejecutar("resumen_de_unidad", {"unidadId": "u1"})

    def test_exige_la_unidad(self) -> None:
        with pytest.raises(ValueError, match="unidadId"):
            _catalogo(ReservasFalsas()).validar("resumen_de_unidad", {})


class TestReservasHttp:
    def _cliente(self, respuesta: httpx.Response, capturas: list[httpx.Request]) -> ReservasHttp:
        def manejador(p: httpx.Request) -> httpx.Response:
            capturas.append(p)
            return respuesta

        return ReservasHttp(
            "http://reservas:8082",
            lambda: "tok-servicio",
            cliente=httpx.Client(transport=httpx.MockTransport(manejador)),
        )

    def test_consulta_la_API_de_Reservas_con_el_token_de_servicio_y_los_filtros(self) -> None:
        capturas: list[httpx.Request] = []
        cuerpo: list[dict[str, Any]] = [
            {
                "id": "r1",
                "areaId": "a",
                "unidadId": "u1",
                "inicio": "2026-11-20T14:00:00Z",
                "fin": "2026-11-20T18:00:00Z",
                "estado": "CONFIRMADA",
                "costoUso": "500.00",
                "garantia": "300.00",
                "cantidadInvitados": 2,
                "version": 0,
            }
        ]

        datos = self._cliente(httpx.Response(200, json=cuerpo), capturas).reservas_de("u1", "CONFIRMADA")

        assert capturas[0].url.path == "/api/reservas"
        assert dict(capturas[0].url.params) == {"unidadId": "u1", "estado": "CONFIRMADA"}
        assert capturas[0].headers["authorization"] == "Bearer tok-servicio"
        assert datos == [
            ReservaDato(
                "r1",
                "a",
                "u1",
                "2026-11-20T14:00:00Z",
                "2026-11-20T18:00:00Z",
                "CONFIRMADA",
                Decimal("500.00"),
                Decimal("300.00"),
                2,
            )
        ]

    def test_acepta_la_lista_envuelta_en_data(self) -> None:
        r = self._cliente(httpx.Response(200, json={"data": []}), []).reservas_de(None, None)

        assert r == []

    @pytest.mark.parametrize(
        "respuesta",
        [
            httpx.Response(503, json={}),
            httpx.Response(200, text="no es json"),
            httpx.Response(200, json=[{"id": "r1"}]),
        ],
    )
    def test_una_respuesta_inutilizable_es_AccionNoDisponible(self, respuesta: httpx.Response) -> None:
        with pytest.raises(AccionNoDisponible):
            self._cliente(respuesta, []).reservas_de("u1", None)

    def test_sin_conexion_es_AccionNoDisponible(self) -> None:
        def cae(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sin red")

        cliente = ReservasHttp(
            "http://reservas:8082", lambda: "t", cliente=httpx.Client(transport=httpx.MockTransport(cae))
        )

        with pytest.raises(AccionNoDisponible, match="Reservas"):
            cliente.reservas_de(None, None)

    def test_el_resultado_se_puede_serializar_para_el_LLM(self) -> None:
        r = _catalogo(ReservasFalsas([_reserva("r1", "CONFIRMADA", "2026-11-20T14:00:00Z")])).ejecutar(
            "consultar_reservas", {}
        )

        assert json.loads(json.dumps(r))["total"] == 1
