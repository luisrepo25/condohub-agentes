"""Lectura de Reservas por su API REST con la cuenta de servicio (solo GET; el agente nunca escribe)."""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.application.herramientas import AccionNoDisponible
from app.application.herramientas_reservas import ReservaDato


class ReservasHttp:
    def __init__(
        self,
        url_base: str,
        token: Callable[[], str],
        cliente: httpx.Client | None = None,
        tiempo_s: float = 20.0,
    ) -> None:
        self._url = url_base.rstrip("/")
        self._token = token
        self._cliente = cliente or httpx.Client(timeout=tiempo_s)

    def reservas_de(self, unidad_id: str | None, estado: str | None) -> list[ReservaDato]:
        filtros = {k: v for k, v in (("unidadId", unidad_id), ("estado", estado)) if v}
        try:
            r = self._cliente.get(
                f"{self._url}/api/reservas",
                params=filtros,
                headers={"Authorization": f"Bearer {self._token()}"},
            )
        except httpx.HTTPError as e:
            raise AccionNoDisponible("No se pudo conectar con Reservas") from e
        if r.status_code != 200:
            raise AccionNoDisponible(f"Reservas respondió HTTP {r.status_code}")
        try:
            cuerpo: Any = r.json()
            lista = cuerpo.get("data", []) if isinstance(cuerpo, dict) else cuerpo
            return [_dato(x) for x in lista]
        except (ValueError, KeyError, TypeError, InvalidOperation) as e:
            raise AccionNoDisponible("Reservas devolvió una respuesta con forma inesperada") from e


def _dato(x: dict[str, Any]) -> ReservaDato:
    return ReservaDato(
        str(x["id"]),
        str(x["areaId"]),
        str(x["unidadId"]),
        str(x["inicio"]),
        str(x["fin"]),
        str(x["estado"]),
        Decimal(x["costoUso"]),
        Decimal(x["garantia"]),
        int(x.get("cantidadInvitados", 0)),
    )
