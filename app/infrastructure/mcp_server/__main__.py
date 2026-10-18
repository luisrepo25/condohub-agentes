"""Servidor MCP por stdio: `python -m app.infrastructure.mcp_server`.

Para que las confirmaciones pendientes las vea la API (y el ADMIN pueda aprobarlas) hay que usar
`PERSISTENCIA=mongo`
con el mismo MongoDB que la API. Con `memoria` las solicitudes viven solo en este proceso.
"""

from app.config_agente import ConfigAgente
from app.config_monitoreo import ConfigMonitoreo
from app.infrastructure.composicion_agente import construir_agente
from app.infrastructure.mcp_server.servidor import crear_servidor


def main() -> None:
    agente = construir_agente(ConfigMonitoreo.desde_entorno(), ConfigAgente.desde_entorno())
    crear_servidor(agente).run("stdio")


if __name__ == "__main__":
    main()
