"""Arma el caso de uso del monitoreo según la configuración (`PERSISTENCIA=memoria|mongo`)."""

from datetime import UTC, datetime
from typing import Any

from app.application.monitoreo import (
    EjecutarMonitoreo,
    InformeRepository,
    ListarInformes,
    MetricasRepository,
    Notificador,
)
from app.config_monitoreo import ConfigMonitoreo
from app.infrastructure.gestion_graphql import GestionGraphQL
from app.infrastructure.memoria import InformesEnMemoria, MetricasEnMemoria
from app.infrastructure.notificador_webhook import NotificadorWebhook, SinNotificador
from app.infrastructure.token_servicio import TokenServicio


class RelojUtc:
    def ahora(self) -> datetime:
        return datetime.now(UTC)


class Monitoreo:
    """Los dos casos de uso del monitoreo, listos para la API y el job."""

    def __init__(self, ejecutar: EjecutarMonitoreo, listar: ListarInformes) -> None:
        self.ejecutar = ejecutar
        self.listar = listar


def _repositorios(config: ConfigMonitoreo) -> tuple[MetricasRepository, InformeRepository]:
    if config.persistencia == "memoria":
        return MetricasEnMemoria(), InformesEnMemoria()
    if config.persistencia == "mongo":
        from pymongo import MongoClient

        from app.infrastructure.mongo.monitoreo import InformesMongo, MetricasMongo

        cliente: MongoClient[dict[str, Any]] = MongoClient(config.mongo_uri, tz_aware=True)
        base = cliente[config.mongo_db]
        return MetricasMongo(base), InformesMongo(base)
    raise ValueError(f"PERSISTENCIA desconocida: {config.persistencia!r} (use «memoria» o «mongo»)")


def construir_monitoreo(config: ConfigMonitoreo) -> Monitoreo:
    metricas, informes = _repositorios(config)
    token = TokenServicio(
        config.keycloak_token_url, config.servicios_client_id, config.servicios_client_secret
    )
    notificador: Notificador = (
        NotificadorWebhook(config.n8n_webhook_alertas) if config.n8n_webhook_alertas else SinNotificador()
    )
    caso = EjecutarMonitoreo(
        GestionGraphQL(config.gestion_graphql_url, token),
        metricas,
        informes,
        notificador,
        RelojUtc(),
        config.parametros,
    )
    return Monitoreo(caso, ListarInformes(informes))
