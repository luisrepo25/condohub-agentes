from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.api.problemas import ProblemaError
from app.api.schemas_mision import ConfirmacionSchema
from app.api.seguridad import requiere_rol, solicitante_actual
from app.application.mision import ConfirmacionNoEncontrada, ConflictoDeVersion, Resolucion
from app.domain.mision import ConfirmacionYaResuelta
from app.domain.roles import Rol, Solicitante
from app.infrastructure.composicion_agente import Agente

# G2 / F5: lo que cree cargos o mueva dinero no se ejecuta sin la aprobación de un ADMIN identificado.
router = APIRouter(
    prefix="/confirmaciones", tags=["Confirmaciones"], dependencies=[Depends(requiere_rol(Rol.ADMIN))]
)


def _agente(request: Request) -> Agente:
    agente: Agente = request.app.state.agente
    return agente


def _responder(resolucion: Resolucion, agente: Agente, tareas: BackgroundTasks) -> ConfirmacionSchema:
    if resolucion.continuar_mision:  # el agente sigue con lo que decidió el ADMIN
        tareas.add_task(agente.ejecutar.ejecutar, resolucion.confirmacion.mision_id)
    return ConfirmacionSchema.desde_dominio(resolucion.confirmacion)


@router.post("/{id}/aprobar", response_model=ConfirmacionSchema, operation_id="aprobarConfirmacion")
def aprobar(
    id: UUID,  # noqa: A002
    tareas: BackgroundTasks,
    solicitante: Annotated[Solicitante, Depends(solicitante_actual)],
    agente: Annotated[Agente, Depends(_agente)],
) -> ConfirmacionSchema:
    """El ADMIN aprueba la acción pendiente; recién entonces se ejecuta. Queda registrado quién y cuándo
    (G3)."""
    try:
        return _responder(agente.aprobar.aprobar(id, solicitante.sub), agente, tareas)
    except ConfirmacionNoEncontrada as e:
        raise ProblemaError(404, "No encontrado", "La confirmación no existe") from e
    except (ConfirmacionYaResuelta, ConflictoDeVersion) as e:
        raise ProblemaError(409, "Conflicto", "La confirmación ya fue resuelta", code="G2") from e


@router.post("/{id}/rechazar", response_model=ConfirmacionSchema, operation_id="rechazarConfirmacion")
def rechazar(
    id: UUID,  # noqa: A002
    tareas: BackgroundTasks,
    solicitante: Annotated[Solicitante, Depends(solicitante_actual)],
    agente: Annotated[Agente, Depends(_agente)],
) -> ConfirmacionSchema:
    """El ADMIN rechaza la acción pendiente: no se ejecuta y el agente lo sabe."""
    try:
        return _responder(agente.rechazar.rechazar(id, solicitante.sub), agente, tareas)
    except ConfirmacionNoEncontrada as e:
        raise ProblemaError(404, "No encontrado", "La confirmación no existe") from e
    except (ConfirmacionYaResuelta, ConflictoDeVersion) as e:
        raise ProblemaError(409, "Conflicto", "La confirmación ya fue resuelta", code="G2") from e
