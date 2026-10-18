"""Servidor MCP: se prueba con un cliente MCP real sobre transporte en memoria. Mismo candado de
confirmación (G2)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from mcp.client import Client

from app.application.mision import (
    ConfirmarAccion,
    ConsultarMision,
    EjecutarMision,
    IniciarMision,
    RechazarAccion,
    SolicitarAccion,
)
from app.domain.mision import EstadoConfirmacion, EstadoMision
from app.infrastructure.composicion_agente import Agente
from app.infrastructure.mcp_server.servidor import crear_servidor
from tests.dobles_mision import Mundo

HERRAMIENTAS = {
    "consultar_morosos",
    "estado_de_cuenta",
    "pagos_pendientes",
    "calcular_recargo",
    "proponer_recargo",
    "enviar_recordatorio",
}


def _agente(mundo: Mundo) -> Agente:
    base = (mundo.misiones, mundo.confirmaciones, mundo.bitacora, mundo.reloj)
    return Agente(
        IniciarMision(*base),
        EjecutarMision(*base, mundo.catalogo, mundo.llm),
        ConfirmarAccion(*base, mundo.catalogo),
        RechazarAccion(*base, mundo.catalogo),
        ConsultarMision(*base),
        SolicitarAccion(*base, mundo.catalogo),
        mundo.catalogo,
        15,
        False,
    )


def _con_cliente(mundo: Mundo, uso: Callable[[Client], Awaitable[Any]]) -> Any:
    async def correr() -> Any:
        async with Client(crear_servidor(_agente(mundo))) as cliente:
            return await uso(cliente)

    return asyncio.run(correr())


def test_G2_el_servidor_expone_las_mismas_herramientas_que_el_agente() -> None:
    herramientas = _con_cliente(Mundo(), lambda c: c.list_tools())
    assert {t.name for t in herramientas.tools} == HERRAMIENTAS
    assert all(t.description for t in herramientas.tools)


def test_G2_las_lecturas_responden_al_instante() -> None:
    r = _con_cliente(Mundo(), lambda c: c.call_tool("consultar_morosos", {"limite": 1}))
    assert (
        not r.is_error and r.structured_content["total"] == 2 and len(r.structured_content["unidades"]) == 1
    )


def test_F5_calcular_recargo_por_mcp_usa_el_porcentaje_del_parametro() -> None:
    r = _con_cliente(Mundo(), lambda c: c.call_tool("calcular_recargo", {"deudaVencida": "390.00"}))
    assert r.structured_content["recargo"] == "7.80"


def test_G2_una_escritura_por_mcp_no_se_ejecuta_queda_pendiente() -> None:
    mundo = Mundo()
    argumentos = {"unidadId": "u1", "mensaje": "Estimado propietario, tiene expensas vencidas."}
    r = _con_cliente(mundo, lambda c: c.call_tool("enviar_recordatorio", argumentos))
    assert not r.is_error and r.structured_content["estado"] == "PENDIENTE_DE_CONFIRMACION"
    assert mundo.recordatorios.enviados == []  # nada salió
    confirmacion = mundo.confirmaciones.obtener(UUID(r.structured_content["confirmacionId"]))
    assert confirmacion and confirmacion.estado is EstadoConfirmacion.PENDIENTE
    mision = mundo.misiones.obtener(confirmacion.mision_id)
    assert mision and mision.estado is EstadoMision.ESPERANDO_CONFIRMACION and mision.iniciada_por == "mcp"


def test_F5_proponer_recargo_por_mcp_tampoco_se_aplica_solo() -> None:
    mundo = Mundo()
    r = _con_cliente(
        mundo,
        lambda c: c.call_tool(
            "proponer_recargo", {"unidadId": "u1", "monto": "7.80", "motivo": "Mora de 1 mes"}
        ),
    )
    assert r.structured_content["estado"] == "PENDIENTE_DE_CONFIRMACION" and mundo.recargos.propuestos == []


def test_G2_la_aprobacion_del_admin_ejecuta_lo_pedido_por_mcp() -> None:
    mundo = Mundo()
    r = _con_cliente(
        mundo, lambda c: c.call_tool("enviar_recordatorio", {"unidadId": "u1", "mensaje": "Hola"})
    )
    ConfirmarAccion(
        mundo.misiones, mundo.confirmaciones, mundo.bitacora, mundo.reloj, mundo.catalogo
    ).aprobar(UUID(r.structured_content["confirmacionId"]), "admin-1")
    assert mundo.recordatorios.enviados == [("u1", "Hola")]


def test_G2_argumentos_invalidos_devuelven_el_motivo_y_no_crean_nada() -> None:
    mundo = Mundo()
    r = _con_cliente(
        mundo, lambda c: c.call_tool("proponer_recargo", {"unidadId": "u1", "monto": "-3", "motivo": "x"})
    )
    assert r.is_error and "monto" in r.content[0].text
    assert mundo.misiones._misiones == {}  # type: ignore[attr-defined]


def test_G2_una_lectura_con_argumentos_invalidos_es_un_error_claro() -> None:
    r = _con_cliente(Mundo(), lambda c: c.call_tool("calcular_recargo", {"deudaVencida": "abc"}))
    assert r.is_error and "deudaVencida" in r.content[0].text
