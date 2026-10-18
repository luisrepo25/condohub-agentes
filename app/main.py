from fastapi import FastAPI

from app.api.problemas import registrar_manejadores
from app.api.routers import confirmaciones, misiones, salud
from app.api.routers import monitoreo as router_monitoreo
from app.application.puertos import VerificadorToken
from app.config import Config
from app.config_agente import ConfigAgente
from app.config_monitoreo import ConfigMonitoreo
from app.infrastructure.composicion import Monitoreo, construir_monitoreo
from app.infrastructure.composicion_agente import Agente, construir_agente
from app.infrastructure.keycloak import JwtVerificador


def create_app(
    verificador: VerificadorToken | None = None, monitoreo: Monitoreo | None = None, agente: Agente | None =
    None
) -> FastAPI:
    """Fábrica de la aplicación. Los tests inyectan el verificador (y, si quieren, el monitoreo)."""
    app = FastAPI(title="CondoHub · Agentes", version="0.1.0")
    if verificador is None:
        config = Config.desde_entorno()
        verificador = JwtVerificador.desde_jwks(config.keycloak_issuer, config.keycloak_jwks)
    app.state.verificador = verificador
    app.state.monitoreo = monitoreo or construir_monitoreo(ConfigMonitoreo.desde_entorno())
    app.state.agente = agente or construir_agente(ConfigMonitoreo.desde_entorno(),
    ConfigAgente.desde_entorno())
    registrar_manejadores(app)
    for router in (salud.router, misiones.router, confirmaciones.router, router_monitoreo.router):
        app.include_router(router)
    return app


app = create_app()
