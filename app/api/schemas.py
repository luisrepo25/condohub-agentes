"""Esquemas de respuesta. Los estados salen de la validación de `db/mongo-init.js`."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class Salud(BaseModel):
    servicio: str
    estado: str


class EstadoMision(StrEnum):
    EN_CURSO = "EN_CURSO"
    ESPERANDO_CONFIRMACION = "ESPERANDO_CONFIRMACION"
    COMPLETADA = "COMPLETADA"
    INCOMPLETA = "INCOMPLETA"
    CANCELADA = "CANCELADA"
    ERROR = "ERROR"


class Mision(BaseModel):
    id: UUID
    tipo: str
    objetivo: str
    estado: EstadoMision


class EstadoConfirmacion(StrEnum):
    PENDIENTE = "PENDIENTE"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"
    EJECUTADA = "EJECUTADA"
    FALLIDA = "FALLIDA"


class Confirmacion(BaseModel):
    id: UUID
    misionId: UUID  # noqa: N815 - nombre del contrato
    herramienta: str
    riesgo: str
    estado: EstadoConfirmacion


class NuevaMision(BaseModel):
    tipo: str = "GESTIONAR_MOROSIDAD"
    objetivo: str
