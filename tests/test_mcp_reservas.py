"""El servidor MCP expone las herramientas de Reservas solo si el agente ve Reservas (E6, C2)."""

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from mcp.client import Client

from app.application.herramientas_reservas import CatalogoConReservas, ReservaDato
from app.application.mision import (
    ConfirmarAccion,
    ConsultarMision,
    EjecutarMision,
    IniciarMision,
    RechazarAccion,
    SolicitarAccion,
)
from app.config_agente import ConfigAgente
from app.infrastructure.composicion_agente import Agente
from app.infrastructure.mcp_server.servidor import crear_servidor
from tests.dobles_mision import Mundo


class ReservasFalsas:
    def reservas_de(self, unidad_id: str | None, estado: str | None) -> list[ReservaDato]:
        return [
            ReservaDato(
                "r1",
                "area-1",
                unidad_id or "u1",
                "2026-11-20T14:00:00Z",
                "2026-11-20T18:00:00Z",
                estado or "CONFIRMADA",
                Decimal("500.00"),
                Decimal("300.00"),
                2,
            )
        ]


def _agente(mundo: Mundo, con_reservas: bool) -> Agente:
    base = (mundo.misiones, mundo.confirmaciones, mundo.bitacora, mundo.reloj)
    catalogo = CatalogoConReservas(mundo.catalogo, ReservasFalsas()) if con_reservas else mundo.catalogo
    return Agente(
        IniciarMision(*base),
        EjecutarMision(*base, catalogo, mundo.llm),
        ConfirmarAccion(*base, catalogo),
        RechazarAccion(*base, catalogo),
        ConsultarMision(*base),
        SolicitarAccion(*base, catalogo),
        catalogo,
        15,
        False,
    )


def _con_cliente(con_reservas: bool, uso: Callable[[Client], Awaitable[Any]]) -> Any:
    async def correr() -> Any:
        async with Client(crear_servidor(_agente(Mundo(), con_reservas))) as cliente:
            return await uso(cliente)

    return asyncio.run(correr())


def test_E6_con_Reservas_el_servidor_expone_8_herramientas_todas_de_lectura_las_nuevas() -> None:
    herramientas = _con_cliente(True, lambda c: c.list_tools())

    nombres = {t.name for t in herramientas.tools}

    assert {"consultar_reservas", "resumen_de_unidad"} <= nombres
    assert len(nombres) == 8


def test_E6_sin_Reservas_el_servidor_sigue_exponiendo_solo_las_6_de_Gestion() -> None:
    herramientas = _con_cliente(False, lambda c: c.list_tools())

    assert len(herramientas.tools) == 6
    assert not {"consultar_reservas", "resumen_de_unidad"} & {t.name for t in herramientas.tools}


def test_C2_un_cliente_MCP_pide_el_resumen_consolidado_de_una_unidad() -> None:
    resultado = _con_cliente(True, lambda c: c.call_tool("resumen_de_unidad", {"unidadId": "u1"}))

    datos = resultado.structured_content
    assert datos["finanzas"]["codigo"] == "B-101"  # lo aporta Gestión
    assert datos["reservas"]["activas"] == 1  # lo aporta Reservas
    assert "sin JOIN" in datos["nota"]


def test_E6_un_cliente_MCP_consulta_las_reservas_con_filtros() -> None:
    resultado = _con_cliente(
        True, lambda c: c.call_tool("consultar_reservas", {"unidadId": "u1", "estado": "CONFIRMADA"})
    )

    assert resultado.structured_content["total"] == 1
    assert resultado.structured_content["reservas"][0]["estado"] == "CONFIRMADA"


@pytest.mark.parametrize("url,esperado", [("", False), ("http://reservas:8082", True)])
def test_la_configuracion_solo_activa_las_herramientas_de_Reservas_con_RESERVAS_URL(
    monkeypatch: pytest.MonkeyPatch, url: str, esperado: bool
) -> None:
    monkeypatch.setenv("RESERVAS_URL", url)

    assert bool(ConfigAgente.desde_entorno().reservas_url) is esperado


def test_el_modelo_por_defecto_ya_no_es_el_que_devolvia_respuestas_vacias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GROQ_MODELO", raising=False)

    assert ConfigAgente.desde_entorno().groq_modelo == "openai/gpt-oss-120b"
