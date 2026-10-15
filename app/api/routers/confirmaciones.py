from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.routers.no_implementado import no_implementado
from app.api.schemas import Confirmacion
from app.api.seguridad import requiere_rol
from app.domain.roles import Rol

# G2 / F5: lo que cree cargos o mueva dinero no se ejecuta sin la aprobación de un ADMIN identificado.
router = APIRouter(
    prefix="/confirmaciones", tags=["Confirmaciones"], dependencies=[Depends(requiere_rol(Rol.ADMIN))]
)


@router.post("/{id}/aprobar", response_model=Confirmacion, operation_id="aprobarConfirmacion")
def aprobar(id: UUID) -> None:  # noqa: A002
    """El ADMIN aprueba la acción pendiente; recién entonces el agente la ejecuta."""
    raise no_implementado("La aprobación de acciones")


@router.post("/{id}/rechazar", response_model=Confirmacion, operation_id="rechazarConfirmacion")
def rechazar(id: UUID) -> None:  # noqa: A002
    """El ADMIN rechaza la acción pendiente."""
    raise no_implementado("El rechazo de acciones")
