import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Configuración por variables de entorno (nunca valores de negocio fijos en el código)."""

    keycloak_issuer: str
    keycloak_jwks: str

    @classmethod
    def desde_entorno(cls) -> "Config":
        issuer = os.environ.get("KEYCLOAK_ISSUER", "http://localhost:8180/realms/condohub")
        return cls(
            keycloak_issuer=issuer,
            keycloak_jwks=os.environ.get("KEYCLOAK_JWKS", f"{issuer}/protocol/openid-connect/certs"),
        )
