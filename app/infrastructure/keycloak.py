"""Verificación de JWT de Keycloak (RS256) contra el JWKS del realm."""

from collections.abc import Callable
from typing import Any

import jwt
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWTError

from app.application.errores import ServicioDeIdentidadNoDisponible, TokenInvalido
from app.domain.roles import Rol, Solicitante

ResolverClave = Callable[[str], Any]


class JwtVerificador:
    """Valida firma, `exp` y `iss`. Los roles salen de `realm_access.roles`; los desconocidos se ignoran."""

    def __init__(self, issuer: str, resolver_clave: ResolverClave) -> None:
        self._issuer = issuer
        self._resolver_clave = resolver_clave

    @classmethod
    def desde_jwks(cls, issuer: str, jwks_uri: str) -> "JwtVerificador":
        cliente = PyJWKClient(jwks_uri, cache_keys=True)
        return cls(issuer, lambda token: cliente.get_signing_key_from_jwt(token).key)

    def verificar(self, token: str) -> Solicitante:
        try:
            clave = self._resolver_clave(token)
            claims = jwt.decode(
                token,
                clave,
                algorithms=["RS256"],
                issuer=self._issuer,
                options={"require": ["exp", "iss", "sub"], "verify_aud": False},
            )
        except PyJWKClientConnectionError as error:
            raise ServicioDeIdentidadNoDisponible(str(error)) from error
        except PyJWTError as error:
            raise TokenInvalido(str(error)) from error
        return Solicitante(sub=str(claims["sub"]), roles=_roles_de(claims))


def _roles_de(claims: dict[str, Any]) -> frozenset[Rol]:
    nombres = (claims.get("realm_access") or {}).get("roles") or []
    conocidos = {rol.value for rol in Rol}
    return frozenset(Rol(nombre) for nombre in nombres if nombre in conocidos)
