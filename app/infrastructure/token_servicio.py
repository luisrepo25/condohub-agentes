"""Token de la cuenta de servicio de Keycloak (`condohub-servicios`, client credentials)."""

import time
from collections.abc import Callable

import httpx

from app.application.monitoreo import GestionNoDisponible

MARGEN_S = 30.0


class TokenServicio:
    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        cliente: httpx.Client | None = None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url, self._id, self._secreto = token_url, client_id, client_secret
        self._cliente = cliente or httpx.Client(timeout=10.0)
        self._reloj = reloj
        self._token: str | None = None
        self._vence = 0.0

    def __call__(self) -> str:
        if self._token is None or self._reloj() >= self._vence:
            self._renovar()
        assert self._token is not None
        return self._token

    def _renovar(self) -> None:
        if not self._secreto:
            raise GestionNoDisponible("Falta el secreto de la cuenta de servicio (SERVICIOS_CLIENT_SECRET)")
        try:
            r = self._cliente.post(
                self._url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._id,
                    "client_secret": self._secreto,
                },
            )
        except httpx.HTTPError as e:
            raise GestionNoDisponible("No se pudo conectar con Keycloak") from e
        if r.status_code != 200:
            raise GestionNoDisponible(f"Keycloak rechazó la cuenta de servicio (HTTP {r.status_code})")
        cuerpo = r.json()
        self._token = str(cuerpo["access_token"])
        self._vence = self._reloj() + max(0.0, float(cuerpo.get("expires_in", 60)) - MARGEN_S)
