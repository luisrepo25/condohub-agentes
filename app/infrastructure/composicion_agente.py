"""Arma el agente de misiones según la configuración (`PERSISTENCIA=memoria|mongo`, igual que el
monitoreo)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.application.herramientas import CatalogoCondohub, CatalogoHerramientas, Herramienta
from app.application.herramientas_reservas import CatalogoConReservas
from app.application.mision import (
    BitacoraRepository,
    ConfirmacionRepository,
    ConfirmarAccion,
    ConsultarMision,
    EjecutarMision,
    IniciarMision,
    LLMNoDisponible,
    LLMPort,
    Mensaje,
    MisionRepository,
    RechazarAccion,
    RespuestaLLM,
    SolicitarAccion,
)
from app.config_agente import ConfigAgente
from app.config_monitoreo import ConfigMonitoreo
from app.infrastructure.acciones import RecordatoriosN8n
from app.infrastructure.gestion_graphql import GestionGraphQL
from app.infrastructure.llm.groq import LLMGroq
from app.infrastructure.memoria_misiones import BitacoraEnMemoria, ConfirmacionesEnMemoria, MisionesEnMemoria
from app.infrastructure.recargos_gestion import RecargosGestion
from app.infrastructure.reservas_http import ReservasHttp
from app.infrastructure.token_servicio import TokenServicio


class _Reloj:
    def ahora(self) -> datetime:
        return datetime.now(UTC)


class LLMNoConfigurado:
    """Sin GROQ_API_KEY el servicio arranca igual; las misiones se rechazan con 503 antes de empezar."""

    def completar(
        self, sistema: str, mensajes: list[Mensaje], herramientas: list[Herramienta]
    ) -> RespuestaLLM:
        raise LLMNoDisponible("El LLM no está configurado (falta GROQ_API_KEY)")


@dataclass(frozen=True)
class Agente:
    """Los casos de uso de las misiones, listos para la API y para el servidor MCP."""

    iniciar: IniciarMision
    ejecutar: EjecutarMision
    aprobar: ConfirmarAccion
    rechazar: RechazarAccion
    consultar: ConsultarMision
    solicitar: SolicitarAccion
    catalogo: CatalogoHerramientas
    limite_pasos: int
    llm_configurado: bool


def _repositorios(
    config: ConfigMonitoreo,
) -> tuple[MisionRepository, ConfirmacionRepository, BitacoraRepository]:
    if config.persistencia == "memoria":
        return MisionesEnMemoria(), ConfirmacionesEnMemoria(), BitacoraEnMemoria()
    if config.persistencia == "mongo":
        from pymongo import MongoClient

        from app.infrastructure.mongo.misiones import BitacoraMongo, ConfirmacionesMongo, MisionesMongo

        cliente: MongoClient[dict[str, Any]] = MongoClient(config.mongo_uri, tz_aware=True)
        base = cliente[config.mongo_db]
        return MisionesMongo(base), ConfirmacionesMongo(base), BitacoraMongo(base)
    raise ValueError(f"PERSISTENCIA desconocida: {config.persistencia!r} (use «memoria» o «mongo»)")


def construir_agente(base: ConfigMonitoreo, config: ConfigAgente) -> Agente:
    misiones, confirmaciones, bitacora = _repositorios(base)
    token = TokenServicio(base.keycloak_token_url, base.servicios_client_id, base.servicios_client_secret)
    catalogo: CatalogoHerramientas = CatalogoCondohub(
        GestionGraphQL(base.gestion_graphql_url, token),
        RecordatoriosN8n(config.n8n_webhook_recordatorios),
        RecargosGestion(base.gestion_graphql_url, token),
        config.recargo_mensual,
    )
    if config.reservas_url:  # E6, C2: lectura de Reservas y reporte consolidado por composición de APIs
        catalogo = CatalogoConReservas(catalogo, ReservasHttp(config.reservas_url, token))
    llm: LLMPort = (
        LLMGroq(config.groq_api_key, config.groq_modelo, config.groq_url_base)
        if config.llm_configurado
        else LLMNoConfigurado()
    )
    reloj = _Reloj()
    repos = (misiones, confirmaciones, bitacora, reloj)
    return Agente(
        iniciar=IniciarMision(*repos),
        ejecutar=EjecutarMision(*repos, catalogo, llm),
        aprobar=ConfirmarAccion(*repos, catalogo),
        rechazar=RechazarAccion(*repos, catalogo),
        consultar=ConsultarMision(*repos),
        solicitar=SolicitarAccion(*repos, catalogo),
        catalogo=catalogo,
        limite_pasos=config.limite_pasos,
        llm_configurado=config.llm_configurado,
    )
