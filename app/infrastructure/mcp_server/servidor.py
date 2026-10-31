"""Servidor MCP de CondoHub: expone las habilidades del agente a cualquier cliente MCP (Claude Desktop, otro
agente...).

Es el mismo catálogo y el mismo candado que usa el agente de misiones (G2): las lecturas responden al
instante; las
escrituras (`enviar_recordatorio`, `proponer_recargo`) **no se ejecutan**: crean una confirmación pendiente
que un ADMIN
debe aprobar en la consola. Ninguna herramienta crea cargos ni mueve dinero por sí sola (F5).
"""

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.application.herramientas import AccionNoDisponible
from app.application.mision import ArgumentosInvalidos
from app.application.monitoreo import GestionNoDisponible
from app.infrastructure.composicion_agente import Agente

INSTRUCCIONES = (
    "Herramientas de gestión del condominio CondoHub. Las de lectura responden al instante. "
    "enviar_recordatorio y proponer_recargo no se ejecutan: quedan pendientes hasta que un ADMIN las apruebe."
)


def _lectura(agente: Agente, herramienta: str, argumentos: dict[str, Any]) -> dict[str, Any]:
    try:
        return agente.catalogo.ejecutar(herramienta, argumentos)
    except (
        ValueError,
        AccionNoDisponible,
        GestionNoDisponible,
    ) as e:  # el cliente recibe el motivo, sin traza
        raise ToolError(str(e)) from e


def _pendiente(agente: Agente, herramienta: str, argumentos: dict[str, Any]) -> dict[str, Any]:
    try:
        confirmacion = agente.solicitar.solicitar(herramienta, argumentos)
    except ArgumentosInvalidos as e:
        raise ToolError(str(e)) from e
    return {
        "estado": "PENDIENTE_DE_CONFIRMACION",
        "confirmacionId": str(confirmacion.id),
        "misionId": str(confirmacion.mision_id),
        "mensaje": "No se ejecutó. Un ADMIN debe aprobarla en la consola de administración (G2).",
    }


def crear_servidor(agente: Agente) -> MCPServer:
    servidor = MCPServer("condohub", instructions=INSTRUCCIONES)

    def descripcion(nombre: str) -> str:
        herramienta = agente.catalogo.obtener(nombre)
        assert herramienta is not None
        return herramienta.descripcion

    @servidor.tool(name="consultar_morosos", description=descripcion("consultar_morosos"))
    def consultar_morosos(limite: int = 20) -> dict[str, Any]:
        return _lectura(agente, "consultar_morosos", {"limite": limite})

    @servidor.tool(name="estado_de_cuenta", description=descripcion("estado_de_cuenta"))
    def estado_de_cuenta(unidadId: str) -> dict[str, Any]:  # noqa: N803 - nombre del contrato
        return _lectura(agente, "estado_de_cuenta", {"unidadId": unidadId})

    @servidor.tool(name="pagos_pendientes", description=descripcion("pagos_pendientes"))
    def pagos_pendientes() -> dict[str, Any]:
        return _lectura(agente, "pagos_pendientes", {})

    @servidor.tool(name="calcular_recargo", description=descripcion("calcular_recargo"))
    def calcular_recargo(deudaVencida: str, meses: int = 1) -> dict[str, Any]:  # noqa: N803
        return _lectura(agente, "calcular_recargo", {"deudaVencida": deudaVencida, "meses": meses})

    @servidor.tool(name="proponer_recargo", description=descripcion("proponer_recargo"))
    def proponer_recargo(unidadId: str, monto: str, motivo: str) -> dict[str, Any]:  # noqa: N803
        return _pendiente(
            agente, "proponer_recargo", {"unidadId": unidadId, "monto": monto, "motivo": motivo}
        )

    @servidor.tool(name="enviar_recordatorio", description=descripcion("enviar_recordatorio"))
    def enviar_recordatorio(unidadId: str, mensaje: str) -> dict[str, Any]:  # noqa: N803
        return _pendiente(agente, "enviar_recordatorio", {"unidadId": unidadId, "mensaje": mensaje})

    if agente.catalogo.obtener("consultar_reservas") is not None:  # solo con RESERVAS_URL

        @servidor.tool(name="consultar_reservas", description=descripcion("consultar_reservas"))
        def consultar_reservas(unidadId: str | None = None, estado: str | None = None) -> dict[str, Any]:  # noqa: N803
            filtros = {k: v for k, v in (("unidadId", unidadId), ("estado", estado)) if v is not None}
            return _lectura(agente, "consultar_reservas", filtros)

        @servidor.tool(name="resumen_de_unidad", description=descripcion("resumen_de_unidad"))
        def resumen_de_unidad(unidadId: str) -> dict[str, Any]:  # noqa: N803
            return _lectura(agente, "resumen_de_unidad", {"unidadId": unidadId})

    return servidor
