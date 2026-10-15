import time
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.infrastructure.keycloak import JwtVerificador
from app.main import create_app

ISSUER = "http://localhost:8180/realms/condohub"

_clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_clave_ajena = rsa.generate_private_key(public_exponent=65537, key_size=2048)

CrearToken = Callable[..., str]


@pytest.fixture(scope="session")
def crear_token() -> CrearToken:
    """Firma tokens como lo haría Keycloak (RS256, `realm_access.roles`, `iss`, `exp`)."""

    def _crear(
        *roles: str,
        sub: str = "00000000-0000-0000-0000-00000000a001",
        issuer: str = ISSUER,
        expira_en: int = 900,
        firmar_con_clave_ajena: bool = False,
    ) -> str:
        ahora = int(time.time())
        claims: dict[str, Any] = {
            "sub": sub,
            "iss": issuer,
            "iat": ahora,
            "exp": ahora + expira_en,
            "realm_access": {"roles": [*roles, "offline_access"]},
        }
        return jwt.encode(claims, _clave_ajena if firmar_con_clave_ajena else _clave, algorithm="RS256")

    return _crear


@pytest.fixture(scope="session")
def client() -> TestClient:
    verificador = JwtVerificador(ISSUER, lambda _token: _clave.public_key())
    return TestClient(create_app(verificador))
