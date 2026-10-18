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

Servidor MCP (stdio) para clientes como Claude Desktop; con `PERSISTENCIA=mongo` las confirmaciones pendientes las ve la API:

```bash
.venv\Scripts\python -m app.infrastructure.mcp_server
```

Misiones con LLM: definir `GROQ_API_KEY`; sin ella `POST /misiones` responde 503.

Arquitectura, reglas, estado y variables: `CLAUDE.md`.