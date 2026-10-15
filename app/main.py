from fastapi import FastAPI

from app.api.problemas import registrar_manejadores
from app.api.routers import confirmaciones, misiones, salud
from app.application.puertos import VerificadorToken
from app.config import Config
from app.infrastructure.keycloak import JwtVerificador


def create_app(verificador: VerificadorToken | None = None) -> FastAPI:
    """Fábrica de la aplicación. Los tests inyectan un verificador con claves propias."""
    app = FastAPI(title="CondoHub · Agentes", version="0.1.0")
    if verificador is None:
        config = Config.desde_entorno()
        verificador = JwtVerificador.desde_jwks(config.keycloak_issuer, config.keycloak_jwks)
    app.state.verificador = verificador
    registrar_manejadores(app)
    for router in (salud.router, misiones.router, confirmaciones.router):
        app.include_router(router)
    return app


app = create_app()
