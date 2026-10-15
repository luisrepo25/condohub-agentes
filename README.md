# condohub-agentes

Agentes de CondoHub: misiones con herramientas MCP y confirmación del ADMIN. FastAPI · Python 3.11 · Clean.

```bash
py -3.11 -m venv .venv && .venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --port 8084
.venv\Scripts\python -m pytest
```

Arquitectura, reglas, estado y variables: `CLAUDE.md`.