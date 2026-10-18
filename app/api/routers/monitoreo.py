"""Agente de monitoreo (G5): ejecutarlo a pedido y consultar sus informes. Solo ADMIN."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.problemas import ProblemaError
from app.api.schemas_monitoreo import InformeMonitoreo
from app.api.seguridad import requiere_rol
from app.application.monitoreo import GestionNoDisponible
from app.domain.monitoreo import Origen
from app.domain.roles import Rol
from app.infrastructure.composicion import Monitoreo

router = APIRouter(prefix="/monitoreo", tags=["Monitoreo"], dependencies=[Depends(requiere_rol(Rol.ADMIN))])


def _monitoreo(request: Request) -> Monitoreo:
    monitoreo: Monitoreo = request.app.state.monitoreo
    return monitoreo


@router.post("/ejecutar", response_model=InformeMonitoreo, operation_id="ejecutarMonitoreo")
def ejecutar(monitoreo: Annotated[Monitoreo, Depends(_monitoreo)]) -> InformeMonitoreo:
    """Corre el agente ahora: lee Gestión, compara con las lecturas anteriores y devuelve el informe."""
    try:
        return InformeMonitoreo.desde_dominio(monitoreo.ejecutar.ejecutar(Origen.MANUAL))
    except GestionNoDisponible as e:
        raise ProblemaError(503, "Gestión no disponible", str(e)) from e


@router.get("/informes", response_model=list[InformeMonitoreo], operation_id="listarInformesMonitoreo")
def listar(
    monitoreo: Annotated[Monitoreo, Depends(_monitoreo)],
    limite: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[InformeMonitoreo]:
    return [InformeMonitoreo.desde_dominio(i) for i in monitoreo.listar.listar(limite)]
