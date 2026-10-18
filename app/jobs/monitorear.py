"""Ejecución programada del agente de monitoreo (G5): `python -m app.jobs.monitorear`.

Programarlo una vez al día: cron, CronJob de Kubernetes, Programador de tareas de Windows o n8n.
Necesita `PERSISTENCIA=mongo` para comparar con días anteriores; con `memoria` cada corrida es línea base.
Código de salida: 0 con informe (haya o no alertas), 1 si Gestión no respondió.
"""

import json
import sys

from app.application.monitoreo import GestionNoDisponible
from app.config_monitoreo import ConfigMonitoreo
from app.domain.monitoreo import Origen
from app.infrastructure.composicion import construir_monitoreo


def main() -> int:
    config = ConfigMonitoreo.desde_entorno()
    if config.persistencia != "mongo":
        print(
            "Aviso: PERSISTENCIA no es «mongo»; las lecturas no se conservan entre ejecuciones.",
            file=sys.stderr,
        )
    try:
        informe = construir_monitoreo(config).ejecutar.ejecutar(Origen.PROGRAMADO)
    except GestionNoDisponible as e:
        print(f"Monitoreo no ejecutado: {e}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "informeId": str(informe.id),
                "alertas": len(informe.alertas),
                "notificado": informe.notificado,
                "resumen": informe.resumen,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
