"""Aviso al ADMIN por n8n (webhook): n8n decide el canal; el agente solo entrega el informe."""

import httpx

from app.application.monitoreo import NotificacionFallida
from app.domain.monitoreo import Informe


class NotificadorWebhook:
    def __init__(self, url: str, cliente: httpx.Client | None = None, tiempo_s: float = 10.0) -> None:
        self._url = url
        self._cliente = cliente or httpx.Client(timeout=tiempo_s)

    def avisar(self, informe: Informe) -> None:
        cuerpo = {
            "informeId": str(informe.id),
            "generadoEn": informe.generado_en.isoformat(),
            "resumen": informe.resumen,
            "alertas": [
                {"tipo": a.tipo.value, "severidad": a.severidad.value, "mensaje": a.mensaje}
                for a in informe.alertas
            ],
        }
        try:
            r = self._cliente.post(self._url, json=cuerpo)
        except httpx.HTTPError as e:
            raise NotificacionFallida("No se pudo llamar al webhook de n8n") from e
        if r.status_code >= 300:
            raise NotificacionFallida(f"n8n respondió HTTP {r.status_code}")


class SinNotificador:
    """Sin webhook configurado: el informe se guarda y se consulta, pero no se avisa por ningún canal."""

    def avisar(self, informe: Informe) -> None:
        raise NotificacionFallida("N8N_WEBHOOK_ALERTAS no está configurado")
