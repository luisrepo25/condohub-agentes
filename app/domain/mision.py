"""Misiones del agente (G1-G3): la misión, las confirmaciones del ADMIN (G2, F5) y la bitácora. Dominio
puro."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

LIMITE_PASOS_POR_DEFECTO = 15


class Riesgo(StrEnum):
    LECTURA = "LECTURA"
    ESCRITURA = "ESCRITURA"
    DINERO = "DINERO"


class TipoMision(StrEnum):
    GESTIONAR_MOROSIDAD = "GESTIONAR_MOROSIDAD"
    LIBRE = "LIBRE"


class EstadoMision(StrEnum):
    EN_CURSO = "EN_CURSO"
    ESPERANDO_CONFIRMACION = "ESPERANDO_CONFIRMACION"
    COMPLETADA = "COMPLETADA"
    INCOMPLETA = "INCOMPLETA"
    CANCELADA = "CANCELADA"
    ERROR = "ERROR"


class EstadoConfirmacion(StrEnum):
    PENDIENTE = "PENDIENTE"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"
    EJECUTADA = "EJECUTADA"
    FALLIDA = "FALLIDA"


class TipoPaso(StrEnum):
    RAZONAMIENTO = "RAZONAMIENTO"
    LLAMADA_HERRAMIENTA = "LLAMADA_HERRAMIENTA"
    RESULTADO_HERRAMIENTA = "RESULTADO_HERRAMIENTA"
    CONFIRMACION = "CONFIRMACION"
    ERROR = "ERROR"
    FIN = "FIN"


class TransicionInvalida(Exception):
    """La operación no es válida en el estado actual de la misión o de la confirmación."""


class ConfirmacionYaResuelta(TransicionInvalida):
    """Otro ADMIN (o este mismo) ya aprobó o rechazó la acción: no se resuelve dos veces (G2)."""


@dataclass
class Mision:
    """Agregado `Mision`: estado, pasos y límite. Sin setters públicos: solo métodos con intención."""

    id: UUID
    tipo: TipoMision
    objetivo: str
    iniciada_por: str
    creada_en: datetime
    limite_pasos: int = LIMITE_PASOS_POR_DEFECTO
    con_llm: bool = True
    estado: EstadoMision = EstadoMision.EN_CURSO
    pasos_ejecutados: int = 0
    resumen: str | None = None
    terminada_en: datetime | None = None

    @classmethod
    def nueva(
        cls,
        tipo: TipoMision,
        objetivo: str,
        iniciada_por: str,
        creada_en: datetime,
        limite_pasos: int = LIMITE_PASOS_POR_DEFECTO,
        con_llm: bool = True,
    ) -> "Mision":
        if not objetivo.strip():
            raise ValueError("La misión necesita un objetivo")
        if not iniciada_por:
            raise ValueError("La misión la inicia un ADMIN identificado")
        if not 1 <= limite_pasos <= 50:
            raise ValueError("El límite de pasos debe estar entre 1 y 50")
        return cls(uuid4(), tipo, objetivo.strip(), iniciada_por, creada_en, limite_pasos, con_llm)

    def _exigir(self, *estados: EstadoMision) -> None:
        if self.estado not in estados:
            raise TransicionInvalida(f"La misión está {self.estado}, no admite esta operación")

    @property
    def alcanzo_el_limite(self) -> bool:
        return self.pasos_ejecutados >= self.limite_pasos

    def registrar_paso(self) -> None:
        self._exigir(EstadoMision.EN_CURSO)
        if self.alcanzo_el_limite:
            raise TransicionInvalida("La misión alcanzó el límite de pasos")
        self.pasos_ejecutados += 1

    def esperar_confirmacion(self) -> None:
        self._exigir(EstadoMision.EN_CURSO)
        self.estado = EstadoMision.ESPERANDO_CONFIRMACION

    def reanudar(self) -> None:
        self._exigir(EstadoMision.ESPERANDO_CONFIRMACION)
        self.estado = EstadoMision.EN_CURSO

    def _terminar(self, estado: EstadoMision, resumen: str, ahora: datetime) -> None:
        self.estado, self.resumen, self.terminada_en = estado, resumen, ahora

    def completar(self, resumen: str, ahora: datetime) -> None:
        self._exigir(EstadoMision.EN_CURSO)
        self._terminar(EstadoMision.COMPLETADA, resumen, ahora)

    def marcar_incompleta(self, motivo: str, ahora: datetime) -> None:
        self._exigir(EstadoMision.EN_CURSO)
        self._terminar(EstadoMision.INCOMPLETA, motivo, ahora)

    def fallar(self, motivo: str, ahora: datetime) -> None:
        self._exigir(EstadoMision.EN_CURSO, EstadoMision.ESPERANDO_CONFIRMACION)
        self._terminar(EstadoMision.ERROR, motivo, ahora)

    def cancelar(self, motivo: str, ahora: datetime) -> None:
        self._exigir(EstadoMision.EN_CURSO, EstadoMision.ESPERANDO_CONFIRMACION)
        self._terminar(EstadoMision.CANCELADA, motivo, ahora)


@dataclass
class ConfirmacionPendiente:
    """Toda herramienta que no es de lectura espera aquí a que un ADMIN identificado la apruebe (G2, F5)."""

    id: UUID
    mision_id: UUID
    herramienta: str
    argumentos: dict[str, Any]
    riesgo: Riesgo
    justificacion: str
    creada_en: datetime
    llamada_id: str | None = None
    estado: EstadoConfirmacion = EstadoConfirmacion.PENDIENTE
    resuelta_por: str | None = None
    resuelta_en: datetime | None = None
    resultado: dict[str, Any] | None = None
    version: int = field(default=0)  # bloqueo optimista: cada cambio de estado la incrementa

    @classmethod
    def nueva(
        cls,
        mision_id: UUID,
        herramienta: str,
        argumentos: dict[str, Any],
        riesgo: Riesgo,
        justificacion: str,
        creada_en: datetime,
        llamada_id: str | None = None,
    ) -> "ConfirmacionPendiente":
        if riesgo is Riesgo.LECTURA:
            raise ValueError("Las herramientas de lectura no necesitan confirmación")
        return cls(uuid4(), mision_id, herramienta, argumentos, riesgo, justificacion, creada_en, llamada_id)

    def _resolver(self, estado: EstadoConfirmacion, admin_sub: str, ahora: datetime) -> None:
        if self.estado is not EstadoConfirmacion.PENDIENTE:
            raise ConfirmacionYaResuelta(f"La confirmación ya está {self.estado}")
        if not admin_sub:
            raise ValueError("Quien resuelve debe ser un ADMIN identificado (G3)")
        self.estado, self.resuelta_por, self.resuelta_en = estado, admin_sub, ahora
        self.version += 1

    def aprobar(self, admin_sub: str, ahora: datetime) -> None:
        self._resolver(EstadoConfirmacion.APROBADA, admin_sub, ahora)

    def rechazar(self, admin_sub: str, ahora: datetime) -> None:
        self._resolver(EstadoConfirmacion.RECHAZADA, admin_sub, ahora)

    @property
    def puede_ejecutarse(self) -> bool:
        return self.estado is EstadoConfirmacion.APROBADA

    def registrar_ejecucion(self, resultado: dict[str, Any]) -> None:
        if not self.puede_ejecutarse:
            raise TransicionInvalida("Solo se ejecuta lo que un ADMIN aprobó (G2)")
        self.estado, self.resultado = EstadoConfirmacion.EJECUTADA, resultado
        self.version += 1

    def registrar_fallo(self, motivo: str) -> None:
        if not self.puede_ejecutarse:
            raise TransicionInvalida("Solo se ejecuta lo que un ADMIN aprobó (G2)")
        self.estado, self.resultado = EstadoConfirmacion.FALLIDA, {"error": motivo}
        self.version += 1


@dataclass(frozen=True)
class PasoBitacora:
    """Un paso del agente (G3): herramienta, entrada, salida y quién confirmó. La bitácora solo se agrega."""

    mision_id: UUID
    paso: int
    tipo: TipoPaso
    fecha: datetime
    herramienta: str | None = None
    entrada: dict[str, Any] | None = None
    salida: dict[str, Any] | None = None
    llamada_id: str | None = None
    confirmacion_id: UUID | None = None
    confirmado_por: str | None = None
