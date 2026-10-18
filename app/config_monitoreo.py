"""Configuración del monitoreo (G5). Los umbrales son parámetros de negocio: variables de entorno."""

import os
from dataclasses import dataclass
from decimal import Decimal

from app.domain.monitoreo import Parametros


@dataclass(frozen=True)
class ConfigMonitoreo:
    persistencia: str
    mongo_uri: str
    mongo_db: str
    gestion_graphql_url: str
    keycloak_token_url: str
    servicios_client_id: str
    servicios_client_secret: str
    n8n_webhook_alertas: str
    parametros: Parametros

    @classmethod
    def desde_entorno(cls) -> "ConfigMonitoreo":
        e = os.environ
        issuer = e.get("KEYCLOAK_ISSUER", "http://localhost:8180/realms/condohub")
        p = Parametros()
        return cls(
            persistencia=e.get("PERSISTENCIA", "memoria"),
            mongo_uri=e.get("MONGO_URI", "mongodb://localhost:27017"),
            mongo_db=e.get("MONGO_DB", "agentes"),
            gestion_graphql_url=e.get("GESTION_GRAPHQL_URL", "http://localhost:8081/graphql"),
            keycloak_token_url=e.get("KEYCLOAK_TOKEN_URL", f"{issuer}/protocol/openid-connect/token"),
            servicios_client_id=e.get("SERVICIOS_CLIENT_ID", "condohub-servicios"),
            servicios_client_secret=e.get("SERVICIOS_CLIENT_SECRET", e.get("CONDOHUB_SERVICIOS_SECRET", "")),
            n8n_webhook_alertas=e.get("N8N_WEBHOOK_ALERTAS", ""),
            parametros=Parametros(
                ventana_historica=int(e.get("MONITOREO_VENTANA", p.ventana_historica)),
                aumento_morosidad=Decimal(e.get("MONITOREO_AUMENTO_MOROSIDAD", str(p.aumento_morosidad))),
                aumento_minimo_unidades=int(
                    e.get("MONITOREO_AUMENTO_MINIMO_UNIDADES", p.aumento_minimo_unidades)
                ),
                aumento_deuda=Decimal(e.get("MONITOREO_AUMENTO_DEUDA", str(p.aumento_deuda))),
                pagos_pendientes_max=int(e.get("MONITOREO_PAGOS_PENDIENTES_MAX", p.pagos_pendientes_max)),
                dias_pago_pendiente_max=int(
                    e.get("MONITOREO_DIAS_PAGO_PENDIENTE_MAX", p.dias_pago_pendiente_max)
                ),
            ),
        )
