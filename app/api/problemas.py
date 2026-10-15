"""Errores en `application/problem+json` (RFC 7807); `code` = código de la regla cuando aplica."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.application.errores import ServicioDeIdentidadNoDisponible, SinPermiso, TokenInvalido

MEDIA_TYPE = "application/problem+json"


class ProblemaError(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None, code: str | None = None) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.code = code


def _respuesta(
    status: int,
    title: str,
    detail: str | None = None,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    cuerpo: dict[str, str | int] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        cuerpo["detail"] = detail
    if code:
        cuerpo["code"] = code
    return JSONResponse(cuerpo, status_code=status, media_type=MEDIA_TYPE, headers=headers)


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ProblemaError)
    async def _problema(_: Request, e: ProblemaError) -> JSONResponse:
        return _respuesta(e.status, e.title, e.detail, e.code)

    @app.exception_handler(TokenInvalido)
    async def _no_autenticado(_: Request, __: TokenInvalido) -> JSONResponse:
        return _respuesta(401, "No autenticado", headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(SinPermiso)
    async def _sin_permiso(_: Request, e: SinPermiso) -> JSONResponse:
        return _respuesta(403, "Sin permiso", str(e))

    @app.exception_handler(ServicioDeIdentidadNoDisponible)
    async def _identidad_caida(_: Request, __: ServicioDeIdentidadNoDisponible) -> JSONResponse:
        return _respuesta(503, "Servicio de identidad no disponible")

    @app.exception_handler(RequestValidationError)
    async def _solicitud_invalida(_: Request, __: RequestValidationError) -> JSONResponse:
        return _respuesta(400, "Solicitud inválida", "Faltan campos o tienen un formato incorrecto")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        titulos = {404: "No encontrado", 405: "Método no permitido"}
        return _respuesta(e.status_code, titulos.get(e.status_code, "Error"))
