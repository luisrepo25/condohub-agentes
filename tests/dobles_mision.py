"""Dobles de prueba para las misiones: un LLM guionado, un catálogo con puertos falsos y un reloj fijo."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.application.herramientas import AccionNoDisponible, CatalogoCondohub, EstadoCuentaDato, Herramienta
from app.application.mision import (
    BitacoraRepository,
    ConfirmacionRepository,
    LlamadaHerramienta,
    LLMNoDisponible,
    Mensaje,
    MisionRepository,
    RespuestaLLM,
)
from app.application.monitoreo import MorosoDato, PagoPendienteDato
from app.infrastructure.memoria_misiones import BitacoraEnMemoria, ConfirmacionesEnMemoria, MisionesEnMemoria

AHORA = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


class RelojFijo:
    def ahora(self) -> datetime:
        return AHORA


def llama(nombre: str, id_: str = "c1", **argumentos: Any) -> RespuestaLLM:
    return RespuestaLLM(llamada=LlamadaHerramienta(id_, nombre, argumentos))


def texto(t: str) -> RespuestaLLM:
    return RespuestaLLM(texto=t)


class LLMGuionado:
    """Responde lo que dicta el guion, en orden, y recuerda lo que recibió (para comprobar qué vio el
    modelo)."""

    def __init__(self, *respuestas: RespuestaLLM | Exception) -> None:
        self._respuestas = list(respuestas)
        self.llamadas: list[list[Mensaje]] = []

    def completar(
        self, sistema: str, mensajes: list[Mensaje], herramientas: list[Herramienta]
    ) -> RespuestaLLM:
        self.llamadas.append(list(mensajes))
        if not self._respuestas:
            raise LLMNoDisponible("Se acabó el guion")
        siguiente = self._respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


class GestionLecturaFalsa:
    def __init__(self) -> None:
        self.morosos_ = [MorosoDato("u1", Decimal("390.00"), 2), MorosoDato("u2", Decimal("120.50"), 1)]

    def morosos(self) -> list[MorosoDato]:
        return self.morosos_

    def pagos_pendientes(self) -> list[PagoPendienteDato]:
        return [PagoPendienteDato("p1", Decimal("80.00"), date(2026, 10, 19))]

    def estado_de_cuenta(self, unidad_id: str) -> EstadoCuentaDato:
        return EstadoCuentaDato(
            unidad_id, "B-101", "B", Decimal("500.00"), Decimal("390.00"), 2, Decimal("0"), True
        )


class RecordatoriosFalsos:
    def __init__(self) -> None:
        self.enviados: list[tuple[str, str]] = []

    def enviar(self, unidad_id: str, mensaje: str) -> dict[str, Any]:
        self.enviados.append((unidad_id, mensaje))
        return {"enviado": True, "unidadId": unidad_id}


class RecargosFalsos:
    def __init__(self, falla: bool = False) -> None:
        self.propuestos: list[tuple[str, Decimal, str]] = []
        self.falla = falla

    def proponer(self, unidad_id: str, monto: Decimal, motivo: str) -> dict[str, Any]:
        if self.falla:
            raise AccionNoDisponible("Gestión aún no publica proponerRecargo")
        self.propuestos.append((unidad_id, monto, motivo))
        return {"propuestaId": "prop-1", "monto": f"{monto:.2f}"}


class Mundo:
    """Todo lo que necesita una misión, en memoria."""

    def __init__(self, llm: LLMGuionado | None = None, recargos: RecargosFalsos | None = None) -> None:
        self.misiones: MisionRepository = MisionesEnMemoria()
        self.confirmaciones: ConfirmacionRepository = ConfirmacionesEnMemoria()
        self.bitacora: BitacoraRepository = BitacoraEnMemoria()
        self.reloj = RelojFijo()
        self.gestion = GestionLecturaFalsa()
        self.recordatorios = RecordatoriosFalsos()
        self.recargos = recargos or RecargosFalsos()
        self.catalogo = CatalogoCondohub(self.gestion, self.recordatorios, self.recargos, Decimal("0.02"))
        self.llm = llm or LLMGuionado()
