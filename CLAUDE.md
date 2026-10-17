# CLAUDE.md — condohub-agentes

Microservicio **Agentes** de CondoHub: contexto de soporte **Agentes**. Ejecuta misiones de gestión con un agente LLM que actúa solo mediante herramientas **MCP**, y expone el **servidor MCP** de CondoHub. Responsable: **Aldana**.

Este repo es independiente. Si está dentro del espacio de trabajo `condohub`, las reglas completas están en `../../docs/negocio/reglas-de-negocio.md` y el contrato en `../../contracts/openapi/agentes.yaml`.

## Stack

Python 3.11 · FastAPI · SDK oficial de MCP para Python (servidor) · SDK de Anthropic (agente con tool use) · httpx + gql (clientes de Gestión, Reservas y Acceso) · Motor (MongoDB) · pytest · ruff · mypy. Dependencias con `uv`.

## Arquitectura: Clean

```
app/
├── domain/              # Mision, PasoMision, ConfirmacionPendiente, Herramienta (con nivel de riesgo)
│   └── ports/           # MisionRepository, LLMPort, HerramientasPort, Clock
├── application/         # IniciarMision, EjecutarPaso, ConfirmarAccion, RechazarAccion
├── infrastructure/
│   ├── llm/             # adaptador del LLM; el modelo y la API key vienen de variables de entorno
│   ├── mcp_server/      # servidor MCP: define las herramientas y las implementa con los clientes
│   ├── clients/         # gestion_graphql.py, reservas_rest.py, acceso_rest.py
│   └── mongo/           # misiones y bitácora
└── api/                 # FastAPI: lanzar misión, ver estado, confirmar/rechazar acción
```

## Herramientas MCP

| Herramienta | Servicio | Riesgo |
|---|---|---|
| `consultar_morosos(periodo, bloque?)` | Gestión (query) | lectura |
| `estado_de_cuenta(unidadId)` | Gestión (query) | lectura |
| `proponer_recargo(unidadId, monto, motivo)` | Gestión (mutation `proponerRecargo`) | **requiere confirmación** |
| `aplicar_recargo(propuestaId)` | Gestión (mutation `confirmarRecargo`) | **requiere confirmación** |
| `enviar_recordatorio(unidadId, mensaje)` | n8n webhook | requiere confirmación |
| `consultar_disponibilidad(area, fecha)` | Reservas | lectura |
| `crear_reserva(...)` | Reservas | requiere confirmación |
| `registrar_visita(...)` | Acceso | requiere confirmación |

Toda herramienta que no sea de lectura **no se ejecuta** cuando el LLM la pide: se crea una `ConfirmacionPendiente` y la misión queda `ESPERANDO_CONFIRMACION` hasta que el `ADMIN` la acepta o rechaza en la consola.

## Base de datos

MongoDB `agentes` en `db/mongo-init.js` (idempotente): `misiones`, `confirmaciones` (el validador exige ADMIN y fecha para aprobar), `bitacora`, `memoria`.

## Reglas de negocio que implementa

| Código | Resumen |
|---|---|
| G1 | Misión de referencia: "Gestiona la morosidad del mes": consultar morosos, calcular recargos, redactar recordatorios, proponer planes de pago |
| G2 | El agente actúa solo por MCP; lo que cree cargos o mueva dinero requiere confirmación del `ADMIN` |
| G3 | Bitácora en MongoDB por paso: herramienta, entrada, salida, quién confirmó y cuándo |
| F5 | Los recargos se proponen; nunca se aplican sin confirmación |

## Comandos

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8084
uv run python -m app.infrastructure.mcp_server     # servidor MCP por stdio (para probar con un cliente MCP)
uv run pytest
uv run ruff check . && uv run mypy app
```

## Convenciones locales

- Tests con un `LLMPort` falso que devuelve llamadas a herramientas predefinidas: `test_G2_mutation_queda_pendiente_de_confirmacion`.
- Límite de pasos por misión (por defecto 15) para evitar bucles; al alcanzarlo la misión termina como `INCOMPLETA`.
- El prompt del sistema del agente vive en `app/infrastructure/llm/prompts/` y cita las reglas G1–G3 y F5.
- Nunca guardar la API key del LLM en el repo ni en MongoDB.

## Estado y seguridad (esqueleto, 14/10/2026)

Los endpoints existen y ya están protegidos por rol; su lógica no: responden `501` (`NO_IMPLEMENTADO`), a quitar al implementar cada uno. El servidor MCP, el LLM y el acceso a MongoDB aún no existen.

- Roles (propuesta de `contracts/openapi/agentes.yaml`, a confirmar con Aldana): `GET /salud` cualquiera · `POST /misiones`, `GET /misiones/{id}`, `POST /confirmaciones/{id}/aprobar`, `POST /confirmaciones/{id}/rechazar`: solo ADMIN (G1, G2). Residente y guardia reciben 403.
- JWT de Keycloak: `app/infrastructure/keycloak.py`; `requiere_rol(...)` en `app/api/seguridad.py`; errores problem+json en `app/api/problemas.py` (mismo patrón que `services/ia`). Los estados de `app/api/schemas.py` salen de `db/mongo-init.js`.
- Comandos reales (no hay `uv` en la máquina de Luis): `py -3.11 -m venv .venv`, `.venv\Scripts\python -m pip install -e ".[dev]"`, `... -m uvicorn app.main:app --port 8084`, `... -m pytest` (26 tests, incluido el de contrato con `agentes.yaml`), `... -m ruff check .`, `... -m mypy`.
- Variables: `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS`. Por el gateway: `http://localhost:8080/agentes/salud` con Bearer.
- Contenedor y CI (16/10/2026): `Dockerfile` en la raíz del repo; `infra/docker-compose.apps.yml` lo levanta junto al resto; `.github/workflows/ci.yml` corre las pruebas y publica la imagen en GHCR desde `main`.
## Código funcional protegido (obligatorio)

Código en `main` con tests en verde **no se reescribe, refactoriza, renombra ni reformatea** si la tarea no lo pide explícitamente. Lo nuevo se agrega extendiendo (clases, métodos o archivos nuevos). Si es inevitable tocar código funcional, **detente antes de editar**, explica qué archivo/líneas y por qué, y espera confirmación; luego haz el mínimo diff. Nunca edites tests existentes para que pase código nuevo. Corre los tests antes y después: todo lo que pasaba debe seguir pasando. En el resumen, lista cada archivo existente que modificaste.
