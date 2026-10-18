"""Repositorios MongoDB de las misiones (colecciones `misiones`, `confirmaciones` y `bitacora` de
`db/mongo-init.js`).

Los ids son uuid en texto (los de la API). Las fechas, en UTC (cliente con `tz_aware=True`). Las
confirmaciones usan
bloqueo optimista con `version`: dos ADMIN no pueden resolver la misma acción (G2).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.application.mision import ConflictoDeVersion
from app.domain.mision import (
    ConfirmacionPendiente,
    EstadoConfirmacion,
    EstadoMision,
    Mision,
    PasoBitacora,
    Riesgo,
    TipoMision,
    TipoPaso,
)


def _utc(fecha: datetime | None) -> datetime | None:
    return fecha if fecha is None or fecha.tzinfo else fecha.replace(tzinfo=UTC)


class MisionesMongo:
    def __init__(self, base: Database[dict[str, Any]]) -> None:
        self._col = base["misiones"]

    def guardar(self, m: Mision) -> None:
        doc: dict[str, Any] = {
            "id": str(m.id),
            "tipo": m.tipo.value,
            "objetivo": m.objetivo,
            "estado": m.estado.value,
            "iniciadaPor": m.iniciada_por,
            "conLlm": m.con_llm,
            "pasosEjecutados": m.pasos_ejecutados,
            "limitePasos": m.limite_pasos,
            "creadaEn": m.creada_en,
            "terminadaEn": m.terminada_en,
        }
        if m.resumen is not None:
            doc["resumen"] = m.resumen
        self._col.replace_one({"id": str(m.id)}, doc, upsert=True)

    def obtener(self, mision_id: UUID) -> Mision | None:
        d = self._col.find_one({"id": str(mision_id)})
        if d is None:
            return None
        return Mision(
            id=UUID(d["id"]),
            tipo=TipoMision(d["tipo"]),
            objetivo=d["objetivo"],
            iniciada_por=d["iniciadaPor"],
            creada_en=_utc(d["creadaEn"]),  # type: ignore[arg-type]
            limite_pasos=int(d["limitePasos"]),
            con_llm=bool(d.get("conLlm", True)),
            estado=EstadoMision(d["estado"]),
            pasos_ejecutados=int(d["pasosEjecutados"]),
            resumen=d.get("resumen"),
            terminada_en=_utc(d.get("terminadaEn")),
        )


class ConfirmacionesMongo:
    def __init__(self, base: Database[dict[str, Any]]) -> None:
        self._col = base["confirmaciones"]

    @staticmethod
    def _doc(c: ConfirmacionPendiente) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "id": str(c.id),
            "misionId": str(c.mision_id),
            "herramienta": c.herramienta,
            "argumentos": c.argumentos,
            "riesgo": c.riesgo.value,
            "estado": c.estado.value,
            "justificacion": c.justificacion,
            "version": c.version,
            "creadaEn": c.creada_en,
            "resueltaPor": c.resuelta_por,
            "resueltaEn": c.resuelta_en,
            "resultado": c.resultado,
        }
        if c.llamada_id:
            doc["llamadaId"] = c.llamada_id
        return doc

    def guardar(self, c: ConfirmacionPendiente) -> None:
        doc = self._doc(c)
        if c.version == 0:
            try:
                self._col.insert_one(doc)
            except DuplicateKeyError as e:
                raise ConflictoDeVersion("La confirmación ya existe") from e
            return
        if self._col.replace_one({"id": str(c.id), "version": c.version - 1}, doc).matched_count == 0:
            raise ConflictoDeVersion("La confirmación cambió mientras se resolvía")

    def obtener(self, confirmacion_id: UUID) -> ConfirmacionPendiente | None:
        d = self._col.find_one({"id": str(confirmacion_id)})
        return None if d is None else self._a_dominio(d)

    def de_mision(self, mision_id: UUID) -> list[ConfirmacionPendiente]:
        return [self._a_dominio(d) for d in self._col.find({"misionId": str(mision_id)}).sort("creadaEn", 1)]

    @staticmethod
    def _a_dominio(d: dict[str, Any]) -> ConfirmacionPendiente:
        return ConfirmacionPendiente(
            id=UUID(d["id"]),
            mision_id=UUID(d["misionId"]),
            herramienta=d["herramienta"],
            argumentos=d["argumentos"],
            riesgo=Riesgo(d["riesgo"]),
            justificacion=d.get("justificacion", ""),
            creada_en=_utc(d["creadaEn"]),  # type: ignore[arg-type]
            llamada_id=d.get("llamadaId"),
            estado=EstadoConfirmacion(d["estado"]),
            resuelta_por=d.get("resueltaPor"),
            resuelta_en=_utc(d.get("resueltaEn")),
            resultado=d.get("resultado"),
            version=int(d.get("version", 0)),
        )


class BitacoraMongo:
    def __init__(self, base: Database[dict[str, Any]]) -> None:
        self._col = base["bitacora"]

    def agregar(self, p: PasoBitacora) -> None:
        doc: dict[str, Any] = {
            "misionId": str(p.mision_id),
            "paso": p.paso,
            "tipo": p.tipo.value,
            "fecha": p.fecha,
        }
        for clave, valor in (
            ("herramienta", p.herramienta),
            ("entrada", p.entrada),
            ("salida", p.salida),
            ("llamadaId", p.llamada_id),
            ("confirmacionId", str(p.confirmacion_id) if p.confirmacion_id else None),
            ("confirmadoPor", p.confirmado_por),
        ):
            if valor is not None:
                doc[clave] = valor
        self._col.insert_one(doc)

    def listar(self, mision_id: UUID) -> list[PasoBitacora]:
        return [
            PasoBitacora(
                mision_id=UUID(d["misionId"]),
                paso=int(d["paso"]),
                tipo=TipoPaso(d["tipo"]),
                fecha=_utc(d["fecha"]),  # type: ignore[arg-type]
                herramienta=d.get("herramienta"),
                entrada=d.get("entrada"),
                salida=d.get("salida"),
                llamada_id=d.get("llamadaId"),
                confirmacion_id=UUID(d["confirmacionId"]) if d.get("confirmacionId") else None,
                confirmado_por=d.get("confirmadoPor"),
            )
            for d in self._col.find({"misionId": str(mision_id)}).sort("paso", 1)
        ]
