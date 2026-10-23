"""`proponer_recargo` contra Gestión: llama a la mutation `proponerRecargo` (F5).

Solo registra la **propuesta**: Gestión no crea ningún cargo hasta que un ADMIN la confirma con
`confirmarRecargo` (F5, G2). Se ejecuta solo después de que el ADMIN aprobó la acción en la misión.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from app.application.herramientas import AccionNoDisponible

MUTACION_PROPONER_RECARGO = (
    "mutation($unidadId: ID!, $monto: Decimal, $motivo: String) { "
    "proponerRecargo(unidadId: $unidadId, monto: $monto, motivo: $motivo) "
    "{ id cargoOrigenId periodo monto estado } }"
)


class RecargosGestion:
    """Envía la propuesta con el monto aprobado: Gestión la rechaza (F5) si no coincide con el que calcula."""

    def __init__(
        self, url: str, token: Callable[[], str], cliente: httpx.Client | None = None, tiempo_s: float = 20.0
    ) -> None:
        self._url = url
        self._token = token
        self._cliente = cliente or httpx.Client(timeout=tiempo_s)

    def proponer(self, unidad_id: str, monto: Decimal, motivo: str) -> dict[str, Any]:
        variables = {"unidadId": unidad_id, "monto": f"{monto:.2f}", "motivo": motivo}
        try:
            r = self._cliente.post(
                self._url,
                json={"query": MUTACION_PROPONER_RECARGO, "variables": variables},
                headers={"Authorization": f"Bearer {self._token()}"},
            )
        except httpx.HTTPError as e:
            raise AccionNoDisponible("No se pudo conectar con Gestión: el recargo no se registró") from e
        if r.status_code != 200:
            raise AccionNoDisponible(f"Gestión respondió HTTP {r.status_code}: el recargo no se registró")
        try:
            cuerpo: dict[str, Any] = r.json()
        except ValueError as e:
            raise AccionNoDisponible("Gestión no devolvió JSON: el recargo no se registró") from e
        if cuerpo.get("errors"):
            error = cuerpo["errors"][0]
            codigo = (error.get("extensions") or {}).get("code", "ERROR")
            raise AccionNoDisponible(f"Gestión rechazó el recargo ({codigo}): {error.get('message', '')}")
        try:
            propuestas = cuerpo["data"]["proponerRecargo"]
            return {
                "propuestaIds": [str(p["id"]) for p in propuestas],
                "monto": f"{sum((Decimal(p['monto']) for p in propuestas), Decimal('0')):.2f}",
                "estado": "PROPUESTO",
                "nota": "Solo es una propuesta: Gestión cobra el recargo cuando el ADMIN lo confirma (F5).",
            }
        except (KeyError, TypeError, ValueError, ArithmeticError) as e:
            raise AccionNoDisponible("Gestión devolvió una respuesta con forma inesperada") from e
