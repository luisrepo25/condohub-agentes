"""Las dos acciones del agente que salen del servicio: el recordatorio (n8n) y la propuesta de recargo
(Gestión).

Se ejecutan solo después de que un ADMIN las aprobó (G2): este módulo no decide nada, solo entrega.
"""

from decimal import Decimal
from typing import Any

import httpx

from app.application.herramientas import AccionNoDisponible


class RecordatoriosN8n:
    """Entrega el recordatorio al flujo de n8n, que busca al propietario titular y lo envía por el canal que
    corresponda."""

    def __init__(self, url: str, cliente: httpx.Client | None = None, tiempo_s: float = 15.0) -> None:
        self._url = url
        self._cliente = cliente or httpx.Client(timeout=tiempo_s)

    def enviar(self, unidad_id: str, mensaje: str) -> dict[str, Any]:
        if not self._url:
            raise AccionNoDisponible(
                "N8N_WEBHOOK_RECORDATORIOS no está configurado: no hay a dónde enviar el recordatorio"
            )
        try:
            r = self._cliente.post(self._url, json={"unidadId": unidad_id, "mensaje": mensaje})
        except httpx.HTTPError as e:
            raise AccionNoDisponible("No se pudo llamar al webhook de n8n") from e
        if r.status_code >= 300:
            raise AccionNoDisponible(f"n8n respondió HTTP {r.status_code}")
        return {"enviado": True, "unidadId": unidad_id}


class RecargosSinMutacion:
    """`proponer_recargo` necesita la mutación `proponerRecargo` de Gestión, que aún no está en
    `schema.graphql`.

    Mientras no exista, aprobar la acción termina `FALLIDA` con este motivo: nunca se simula un recargo (F5).
    """

    def proponer(self, unidad_id: str, monto: Decimal, motivo: str) -> dict[str, Any]:
        raise AccionNoDisponible(
            "Gestión aún no publica la mutación proponerRecargo (contracts/graphql/schema.graphql): "
            "el recargo no se registró"
        )
