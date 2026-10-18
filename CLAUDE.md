# CLAUDE.md — condohub-agentes

Microservicio **Agentes** de CondoHub: contexto de soporte **Agentes**. Ejecuta misiones de gestión con un agente LLM que actúa solo mediante herramientas **MCP**, y expone el **servidor MCP** de CondoHub. Responsable: **Aldana**.

Este repo es independiente. Si está dentro del espacio de trabajo `condohub`, las reglas completas están en `../../docs/negocio/reglas-de-negocio.md` y el contrato en `../../contracts/openapi/agentes.yaml`.

## Stack

Python 3.11 · FastAPI · SDK oficial de MCP para Python (servidor) · SDK de Anthropic (agente con tool use) · httpx + gql (clientes de Gestión, Reservas y Acceso) · pymongo (MongoDB; el monitoreo ya lo usa) · pytest · ruff · mypy. Dependencias con `uv`.

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
| G5 | **Agente de monitoreo**: observa y avisa, nunca actúa. Lee morosos y pagos `PENDIENTE`, los compara con las últimas 3 lecturas, genera alertas e informes y avisa al ADMIN por n8n |
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
- Comandos reales (no hay `uv` en la máquina de Luis): `py -3.11 -m venv .venv`, `.venv\Scripts\python -m pip install -e ".[dev]"`, `... -m uvicorn app.main:app --port 8084`, `... -m pytest` (86 tests, incluido el de contrato con `agentes.yaml` y los de integración con Mongo), `... -m ruff check .`, `... -m mypy`.
- Variables: `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS`. Por el gateway: `http://localhost:8080/agentes/salud` con Bearer.
- Contenedor y CI (16/10/2026): `Dockerfile` en la raíz del repo; `infra/docker-compose.apps.yml` lo levanta junto al resto; `.github/workflows/ci.yml` corre las pruebas y publica la imagen en GHCR desde `main`.
## Agente de monitoreo (G5) — implementado el 18/10/2026

Es el agente **autónomo** del requisito E.1 (metas, habilidades y reportes sin que nadie lo lance). **Observa y avisa, nunca actúa**: no crea cargos ni recargos ni mueve dinero (F5, G2). Meta: vigilar la salud financiera del condominio.
Habilidades (solo lectura, GraphQL de Gestión con la cuenta de servicio `condohub-servicios`): `morosos` y `pagosPendientes` (ya publicadas en `schema.graphql`).

- **Qué hace en cada ejecución:** lee los datos, calcula una lectura de métricas, la compara con el promedio de las últimas 3 y guarda un **informe** (métricas, alertas, resumen); si hay alertas, avisa por el webhook de n8n. Alertas: morosidad creciente (≥ 20 % y ≥ 2 unidades), deuda vencida creciente (≥ 20 %), pagos sin conciliar (≥ 5, o alguno con ≥ 3 días). `ALTA` si se supera el doble del umbral. La primera lectura es línea base. Los umbrales son parámetros (variables `MONITOREO_*`).
- **Capas:** dominio `domain/monitoreo.py` (`Metricas`, `Parametros`, `Alerta`, `Informe`, servicio `DetectorAnomalias`); aplicación `application/monitoreo.py` (`EjecutarMonitoreo`, `ListarInformes`, puertos `GestionPort`, `MetricasRepository`, `InformeRepository`, `Notificador`); adaptadores en `infrastructure/` (`gestion_graphql.py`, `token_servicio.py`, `notificador_webhook.py`, `memoria.py`, `mongo/monitoreo.py`, `composicion.py`); API `api/routers/monitoreo.py`; job `app/jobs/monitorear.py`.
- **API (solo ADMIN, contrato `agentes.yaml`):** `POST /monitoreo/ejecutar` (corre el agente y devuelve el informe; 503 si Gestión no responde) y `GET /monitoreo/informes?limite=`.
- **Programarlo (autónomo):** `python -m app.jobs.monitorear` una vez al día (cron, CronJob, Programador de tareas de Windows o un flujo de n8n). Salida JSON en ASCII y código de salida 1 si Gestión no respondió.
- **Variables:** `PERSISTENCIA=memoria|mongo` (sin `mongo` no hay historia entre ejecuciones), `MONGO_URI`, `MONGO_DB`, `GESTION_GRAPHQL_URL`, `KEYCLOAK_TOKEN_URL`, `SERVICIOS_CLIENT_ID` (`condohub-servicios`), `SERVICIOS_CLIENT_SECRET` (o `CONDOHUB_SERVICIOS_SECRET`), `N8N_WEBHOOK_ALERTAS` (sin él se guarda el informe pero no se avisa) y los umbrales `MONITOREO_VENTANA`, `MONITOREO_AUMENTO_MOROSIDAD`, `MONITOREO_AUMENTO_MINIMO_UNIDADES`, `MONITOREO_AUMENTO_DEUDA`, `MONITOREO_PAGOS_PENDIENTES_MAX`, `MONITOREO_DIAS_PAGO_PENDIENTE_MAX`.
- **Base de datos:** colecciones `metricas` e `informes` en `db/mongo-init.js` (validador; dinero en `Decimal128`). `AGENTES_DB=agentes_pruebas` aplica el script sobre otra base para las pruebas de integración.
- **Verificado (18/10/2026):** 86 pruebas (26 originales intactas + 60 nuevas; `tests/integracion` contra MongoDB real), `ruff` y `mypy` limpios. Prueba de punta a punta con el job real, MongoDB real y un Gestión/n8n simulados: 3 corridas normales sin alertas y, al empeorar los datos, 3 alertas `ALTA` avisadas y 4 informes guardados. Ese ensayo destapó un fallo (el job se caía al imprimir `→` en la consola cp1252 de Windows), ya corregido y con prueba.
- **No verificado:** contra el Gestión real (Java) ni con un token real de Keycloak; el webhook de n8n existe solo como URL configurable, **falta crear el flujo de n8n que reciba el aviso y mande el correo** (`infra/n8n`, de Erick/Luis). Los umbrales de G5 son una **propuesta** pendiente de confirmar con Aldana y Erick (`TODO(regla)`).
- **Pendiente (etapa B, requiere tocar `tests/test_roles.py`):** misiones con LLM, confirmaciones de ADMIN y servidor MCP. Los cuatro endpoints actuales siguen respondiendo `501`, y `test_roles.py` lo exige; implementarlos obliga a cambiar esas expectativas (hay que confirmarlo). Además, las herramientas `proponer_recargo` y `aplicar_recargo` de la tabla de arriba no tienen mutaciones en `contracts/graphql/schema.graphql`: hay que definirlas con Aldana antes de implementarlas.

## Código funcional protegido (obligatorio)

Código en `main` con tests en verde **no se reescribe, refactoriza, renombra ni reformatea** si la tarea no lo pide explícitamente. Lo nuevo se agrega extendiendo (clases, métodos o archivos nuevos). Si es inevitable tocar código funcional, **detente antes de editar**, explica qué archivo/líneas y por qué, y espera confirmación; luego haz el mínimo diff. Nunca edites tests existentes para que pase código nuevo. Corre los tests antes y después: todo lo que pasaba debe seguir pasando. En el resumen, lista cada archivo existente que modificaste.
