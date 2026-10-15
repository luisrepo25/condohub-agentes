from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.schemas import Salud
from app.api.seguridad import solicitante_actual
from app.domain.roles import Solicitante

router = APIRouter(tags=["Salud"])


@router.get("/salud", response_model=Salud, operation_id="salud")
def salud(_: Annotated[Solicitante, Depends(solicitante_actual)]) -> Salud:
    """Estado del servicio ("hola" del hito H1). Cualquier rol autenticado."""
    return Salud(servicio="agentes", estado="OK")
