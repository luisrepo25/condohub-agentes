"""Repositorios en memoria de las misiones (`PERSISTENCIA=memoria`: se pierden al reiniciar).

Guardan copias, como lo haría una base de datos, y las confirmaciones aplican el mismo bloqueo optimista que
MongoDB.
"""

from copy import deepcopy
from uuid import UUID

from app.application.mision import ConflictoDeVersion
from app.domain.mision import ConfirmacionPendiente, Mision, PasoBitacora


class MisionesEnMemoria:
    def __init__(self) -> None:
        self._misiones: dict[UUID, Mision] = {}

    def guardar(self, mision: Mision) -> None:
        self._misiones[mision.id] = deepcopy(mision)

    def obtener(self, mision_id: UUID) -> Mision | None:
        mision = self._misiones.get(mision_id)
        return deepcopy(mision) if mision else None


class ConfirmacionesEnMemoria:
    def __init__(self) -> None:
        self._confirmaciones: dict[UUID, ConfirmacionPendiente] = {}

    def guardar(self, confirmacion: ConfirmacionPendiente) -> None:
        existente = self._confirmaciones.get(confirmacion.id)
        if existente is None:
            if confirmacion.version != 0:
                raise ConflictoDeVersion("La confirmación no existe")
        elif existente.version != confirmacion.version - 1:
            raise ConflictoDeVersion("La confirmación cambió mientras se resolvía")
        self._confirmaciones[confirmacion.id] = deepcopy(confirmacion)

    def obtener(self, confirmacion_id: UUID) -> ConfirmacionPendiente | None:
        confirmacion = self._confirmaciones.get(confirmacion_id)
        return deepcopy(confirmacion) if confirmacion else None

    def de_mision(self, mision_id: UUID) -> list[ConfirmacionPendiente]:
        pendientes = [c for c in self._confirmaciones.values() if c.mision_id == mision_id]
        return [deepcopy(c) for c in sorted(pendientes, key=lambda c: c.creada_en)]


class BitacoraEnMemoria:
    def __init__(self) -> None:
        self._pasos: dict[UUID, list[PasoBitacora]] = {}

    def agregar(self, paso: PasoBitacora) -> None:
        self._pasos.setdefault(paso.mision_id, []).append(paso)

    def listar(self, mision_id: UUID) -> list[PasoBitacora]:
        return sorted(self._pasos.get(mision_id, []), key=lambda p: p.paso)
