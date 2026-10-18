"""Esquemas de las misiones y confirmaciones (G1-G3). camelCase como en `contracts/openapi/agentes.yaml`."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.application.mision import VistaMision
from app.domain.mision import ConfirmacionPendiente, EstadoConfirmacion, PasoBitacora


class NuevaMisionSchema(BaseModel):
    tipo: str = "GESTIONAR_MOROSIDAD"
    objetivo: str = Field(min_length=1, max_length=500)


class ConfirmacionSchema(BaseModel):
    id: UUID
    misionId: UUID
    herramienta: str
    argumentos: dict[str, Any] = {}
    riesgo: str
    estado: str
    justificacion: str | None = None
    resueltaPor: str | None = None
    resueltaEn: datetime | None = None
    resultado: dict[str, Any] | None = None

    @classmethod
    def desde_dominio(cls, c: ConfirmacionPendiente) -> "ConfirmacionSchema":
        return cls(
            id=c.id,
            misionId=c.mision_id,
            herramienta=c.herramienta,
            argumentos=c.argumentos,
            riesgo=c.riesgo.value,
            estado=c.estado.value,
            justificacion=c.justificacion,
            resueltaPor=c.resuelta_por,
            resueltaEn=c.resuelta_en,
            resultado=c.resultado,
        )


class PasoSchema(BaseModel):
    paso: int
    tipo: str
    fecha: datetime
    herramienta: str | None = None
    entrada: dict[str, Any] | None = None
    salida: dict[str, Any] | None = None
    confirmadoPor: str | None = None

    @classmethod
    def desde_dominio(cls, p: PasoBitacora) -> "PasoSchema":
        return cls(
            paso=p.paso,
            tipo=p.tipo.value,
            fecha=p.fecha,
            herramienta=p.herramienta,
            entrada=p.entrada,
            salida=p.salida,
            confirmadoPor=p.confirmado_por,
        )


class MisionSchema(BaseModel):
    id: UUID
    tipo: str
    objetivo: str
    estado: str
    resumen: str | None = None
    pasosEjecutados: int = 0
    confirmacionesPendientes: list[ConfirmacionSchema] = []
    pasos: list[PasoSchema] = []

    @classmethod
    def desde_vista(cls, v: VistaMision) -> "MisionSchema":
        m = v.mision
        return cls(
            id=m.id,
            tipo=m.tipo.value,
            objetivo=m.objetivo,
            estado=m.estado.value,
            resumen=m.resumen,
            pasosEjecutados=m.pasos_ejecutados,
            confirmacionesPendientes=[
                ConfirmacionSchema.desde_dominio(c)
                for c in v.confirmaciones
                if c.estado is EstadoConfirmacion.PENDIENTE
            ],
            pasos=[PasoSchema.desde_dominio(p) for p in v.pasos],
        )
