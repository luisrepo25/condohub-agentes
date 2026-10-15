from typing import Protocol

from app.domain.roles import Solicitante


class VerificadorToken(Protocol):
    def verificar(self, token: str) -> Solicitante:
        """Devuelve el solicitante o lanza `TokenInvalido` / `ServicioDeIdentidadNoDisponible`."""
        ...
