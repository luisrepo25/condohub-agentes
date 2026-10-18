# condohub-agentes

Agentes de CondoHub: misiones con herramientas MCP y confirmación del ADMIN. FastAPI · Python 3.11 · Clean.

```bash
py -3.11 -m venv .venv && .venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --port 8084
.venv\Scripts\python -m pytest
```

Agente de monitoreo (G5), una vez al día con el programador de tareas, cron o n8n (necesita `PERSISTENCIA=mongo`, Gestión y Keycloak):

```bash
.venvScriptspython -m app.jobs.monitorear
```

Arquitectura, reglas, estado y variables: `CLAUDE.md`.