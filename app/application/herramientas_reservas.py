"""Herramientas del agente sobre Reservas (solo lectura) y el reporte consolidado entre servicios (E6, C2).

Gestión y Reservas son contextos con su propia base de datos: no hay JOIN entre ellas. El agente llama a
cada API con su contrato y combina las respuestas (composición de APIs); cada contexto conserva sus
datos. Ninguna herramienta de aquí escribe: Reservas solo se consulta desde el agente (G2).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from app.application.herramientas import CatalogoHerramientas, Herramienta, _entero, _objeto, _texto
from app.domain.mision import Riesgo

ESTADOS = ("SOLICITADA", "CONFIRMADA", "FALLIDA", "CANCELADA", "FINALIZADA")
ACTIVAS = ("SOLICITADA", "CONFIRMADA")
PROXIMAS = 5


@dataclass(frozen=True)
class ReservaDato:
    id: str
    area_id: str
    unidad_id: str
    inicio: str
    fin: str
    estado: str
    costo_uso: Decimal
    garantia: Decimal
    invitados: int


class ReservasLectura(Protocol):
    """Lectura de la API REST de Reservas (la saga y las escrituras no son del agente)."""

    def reservas_de(self, unidad_id: str | None, estado: str | None) -> list[ReservaDato]: ...


_UNIDAD = {"type": "string", "description": "Identificador de la unidad (unidadId de Gestión)"}

HERRAMIENTAS_RESERVAS = (
    Herramienta(
        "consultar_reservas",
        "Lista las reservas de áreas comunes (salón, piscina, churrasqueras), de una unidad o de todas, "
        "con su "
        "estado. Solo lectura.",
        _objeto(
            {"unidadId": _UNIDAD, "estado": {"type": "string", "enum": list(ESTADOS)}},
            [],
        ),
        Riesgo.LECTURA,
    ),
    Herramienta(
        "resumen_de_unidad",
        "Resumen consolidado de una unidad: su estado de cuenta (Gestión) y sus reservas (Reservas) "
        "en una sola "
        "respuesta. Solo lectura.",
        _objeto({"unidadId": _UNIDAD}, ["unidadId"]),
        Riesgo.LECTURA,
    ),
)


def _reserva(r: ReservaDato) -> dict[str, Any]:
    return {
        "id": r.id,
        "areaId": r.area_id,
        "inicio": r.inicio,
        "fin": r.fin,
        "estado": r.estado,
        "costoUso": f"{r.costo_uso:.2f}",
        "garantia": f"{r.garantia:.2f}",
        "invitados": r.invitados,
    }


class CatalogoConReservas:
    """Suma las herramientas de Reservas a un catálogo existente sin modificarlo: lo demás se delega."""

    def __init__(self, base: CatalogoHerramientas, reservas: ReservasLectura) -> None:
        self._base = base
        self._reservas = reservas
        self._propias = {h.nombre: h for h in HERRAMIENTAS_RESERVAS}

    def listar(self) -> list[Herramienta]:
        return [*self._base.listar(), *HERRAMIENTAS_RESERVAS]

    def obtener(self, nombre: str) -> Herramienta | None:
        return self._propias.get(nombre) or self._base.obtener(nombre)

    def validar(self, nombre: str, argumentos: dict[str, Any]) -> None:
        if nombre not in self._propias:
            return self._base.validar(nombre, argumentos)
        if nombre == "resumen_de_unidad":
            _texto(argumentos, "unidadId", 100)
        elif "estado" in argumentos and argumentos["estado"] not in ESTADOS:
            raise ValueError(f"«estado» debe ser uno de {', '.join(ESTADOS)}")
        return None

    def ejecutar(self, nombre: str, argumentos: dict[str, Any]) -> dict[str, Any]:
        if nombre not in self._propias:
            return self._base.ejecutar(nombre, argumentos)
        self.validar(nombre, argumentos)
        return (
            self._resumen_de_unidad(argumentos)
            if nombre == "resumen_de_unidad"
            else self._consultar(argumentos)
        )

    def _consultar(self, a: dict[str, Any]) -> dict[str, Any]:
        unidad = _texto(a, "unidadId", 100) if "unidadId" in a else None
        reservas = self._reservas.reservas_de(unidad, a.get("estado"))
        limite = _entero(a, "limite", 50, 1, 50)
        return {"total": len(reservas), "reservas": [_reserva(r) for r in reservas[:limite]]}

    def _resumen_de_unidad(self, a: dict[str, Any]) -> dict[str, Any]:
        unidad = _texto(a, "unidadId", 100)
        finanzas = self._base.ejecutar("estado_de_cuenta", {"unidadId": unidad})
        reservas = self._reservas.reservas_de(unidad, None)
        activas = sorted((r for r in reservas if r.estado in ACTIVAS), key=lambda r: r.inicio)
        return {
            "unidadId": unidad,
            "finanzas": finanzas,
            "reservas": {
                "total": len(reservas),
                "activas": len(activas),
                "proximas": [_reserva(r) for r in activas[:PROXIMAS]],
            },
            "nota": ("Consolidado por composición de APIs: cada contexto conserva sus datos (sin JOIN)."),
        }
