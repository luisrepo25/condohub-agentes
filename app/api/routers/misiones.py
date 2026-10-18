from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.api.problemas import ProblemaError
from app.api.schemas_mision import MisionSchema, NuevaMisionSchema
from app.api.seguridad import requiere_rol, solicitante_actual
from app.application.mision import MisionNoEncontrada, VistaMision
from app.domain.mision import TipoMision
from app.domain.roles import Rol, Solicitante
from app.infrastructure.composicion_agente import Agente

# Solo el ADMIN lanza y consulta misiones (G1, G2). Roles propuestos: a confirmar al escribir agentes.yaml.
router = APIRouter(prefix="/misiones", tags=["Misiones"], dependencies=[Depends(requiere_rol(Rol.ADMIN))])


def _agente(request: Request) -> Agente:
    agente: Agente = request.app.state.agente
    return agente


@router.post("", status_code=202, response_model=MisionSchema, operation_id="lanzarMision")
def lanzar_mision(
    datos: NuevaMisionSchema,
    tareas: BackgroundTasks,
    solicitante: Annotated[Solicitante, Depends(solicitante_actual)],
    agente: Annotated[Agente, Depends(_agente)],
) -> MisionSchema:
    """Lanza una misión, por ejemplo «Gestiona la morosidad del mes» (G1). Se ejecuta en segundo plano."""
    try:
        tipo = TipoMision(datos.tipo)
    except ValueError as e:
        raise ProblemaError(400, "Solicitud inválida", f"Tipo de misión desconocido: {datos.tipo}") from e
    if not agente.llm_configurado:
        raise ProblemaError(503, "LLM no disponible", "El LLM no está configurado (falta GROQ_API_KEY)")
    mision = agente.iniciar.iniciar(solicitante.sub, tipo, datos.objetivo, agente.limite_pasos)
    tareas.add_task(agente.ejecutar.ejecutar, mision.id)
    return MisionSchema.desde_vista(VistaMision(mision, [], []))


@router.get("/{id}", response_model=MisionSchema, operation_id="obtenerMision")
def obtener_mision(id: UUID, agente: Annotated[Agente, Depends(_agente)]) -> MisionSchema:  # noqa: A002 - nombre del contrato
    """Estado de una misión, sus pasos (bitácora, G3) y sus confirmaciones pendientes."""
    try:
        return MisionSchema.desde_vista(agente.consultar.ver(id))
    except MisionNoEncontrada as e:
        raise ProblemaError(404, "No encontrado", "La misión no existe") from e
