from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.routers.no_implementado import no_implementado
from app.api.schemas import Mision, NuevaMision
from app.api.seguridad import requiere_rol
from app.domain.roles import Rol

# Solo el ADMIN lanza y consulta misiones (G1, G2). Roles propuestos: a confirmar al escribir agentes.yaml.
router = APIRouter(prefix="/misiones", tags=["Misiones"], dependencies=[Depends(requiere_rol(Rol.ADMIN))])


@router.post("", status_code=202, response_model=Mision, operation_id="lanzarMision")
def lanzar_mision(mision: NuevaMision) -> None:
    """Lanza una misión, por ejemplo «Gestiona la morosidad del mes» (G1)."""
    raise no_implementado("El lanzamiento de misiones")


@router.get("/{id}", response_model=Mision, operation_id="obtenerMision")
def obtener_mision(id: UUID) -> None:  # noqa: A002 - nombre del contrato
    """Estado de una misión y sus pasos (bitácora, G3)."""
    raise no_implementado("La consulta de misiones")
