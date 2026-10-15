"""Dependencias de FastAPI: autenticación por JWT y autorización por rol."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.autorizacion import exigir_algun_rol
from app.application.errores import TokenInvalido
from app.application.puertos import VerificadorToken
from app.domain.roles import Rol, Solicitante

_esquema = HTTPBearer(auto_error=False)


def solicitante_actual(
    request: Request,
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_esquema)],
) -> Solicitante:
    if credenciales is None:
        raise TokenInvalido("Falta el header Authorization: Bearer")
    verificador: VerificadorToken = request.app.state.verificador
    return verificador.verificar(credenciales.credentials)


def requiere_rol(*permitidos: Rol) -> Callable[[Solicitante], Solicitante]:
    def dependencia(solicitante: Annotated[Solicitante, Depends(solicitante_actual)]) -> Solicitante:
        exigir_algun_rol(solicitante, *permitidos)
        return solicitante

    return dependencia
