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

## Estado y seguridad (actualizado el 18/10/2026)

Todos los endpoints del contrato están implementados y protegidos por rol (ya ninguno responde `501`): el agente de monitoreo (G5) y las misiones con LLM, confirmaciones del ADMIN y servidor MCP (G1-G3, F5). Ver las dos secciones siguientes.

- Roles (propuesta de `contracts/openapi/agentes.yaml`, a confirmar con Aldana): `GET /salud` cualquiera · `POST /misiones`, `GET /misiones/{id}`, `POST /confirmaciones/{id}/aprobar`, `POST /confirmaciones/{id}/rechazar`: solo ADMIN (G1, G2). Residente y guardia reciben 403.
- JWT de Keycloak: `app/infrastructure/keycloak.py`; `requiere_rol(...)` en `app/api/seguridad.py`; errores problem+json en `app/api/problemas.py` (mismo patrón que `services/ia`). Los estados de `app/api/schemas.py` salen de `db/mongo-init.js`.
- Comandos reales (no hay `uv` en la máquina de Luis): `py -3.11 -m venv .venv`, `.venv\Scripts\python -m pip install -e ".[dev]"`, `... -m uvicorn app.main:app --port 8084`, `... -m pytest` (210 tests: 198 sin Mongo y 12 de integración; incluye el de contrato con `agentes.yaml`), `... -m ruff check .`, `... -m mypy`.
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
- **No verificado:** contra el Gestión real (Java) ni con un token real de Keycloak; el webhook de n8n existe solo como URL configurable, **falta crear el flujo de n8n que reciba el aviso y mande el correo** (`infra/n8n`, de Erick/Luis). Los umbrales de G5 son parámetros: decididos por Luis el 31/10/2026, y Aldana y Erick siguen esta decisión.
- La etapa B (misiones, confirmaciones y MCP) se implementó después: ver «Misiones, confirmaciones y servidor MCP».

## Misiones, confirmaciones y servidor MCP (G1–G3, F5) — implementado el 18/10/2026

El agente con LLM del requisito E.1 (metas, habilidades y bitácora). **Regla de oro (G2): el LLM solo actúa por el catálogo de herramientas, y lo que no es lectura NO se ejecuta al pedirlo**: queda como `ConfirmacionPendiente` hasta que un ADMIN identificado lo aprueba.

- **Flujo:** `POST /misiones` (202, ADMIN) crea la misión y el agente trabaja en segundo plano: LLM → herramienta → resultado → LLM. Las lecturas se ejecutan al instante; una escritura o de dinero deja la misión en `ESPERANDO_CONFIRMACION`. `POST /confirmaciones/{id}/aprobar` la ejecuta **una sola vez** (bloqueo optimista con `version`: una segunda resolución da 409 con `code: G2`) y el agente continúa; `rechazar` no ejecuta nada y el agente se entera. `GET /misiones/{id}` devuelve estado, resumen, bitácora (`pasos`) y acciones pendientes. Si no hay `GROQ_API_KEY`, `POST /misiones` responde 503 sin crear nada. Límite de pasos (15 por defecto): al alcanzarlo, `INCOMPLETA`.
- **G3, bitácora:** cada paso queda en `bitacora` (llamada, resultado, confirmación, `confirmadoPor`). La conversación con el LLM **se reconstruye desde la bitácora** al reanudar, así que sobrevive a la espera del ADMIN y a un reinicio. Un error inesperado deja la misión en `ERROR` con su rastro (nunca «en curso» para siempre).
- **Herramientas implementadas** (`application/herramientas.py`): lectura → `consultar_morosos`, `estado_de_cuenta`, `pagos_pendientes` (Gestión, solo `query`) y `calcular_recargo` (F5: interés simple mensual, parámetro `RECARGO_MENSUAL`, 2 % inicial; solo calcula); con confirmación → `enviar_recordatorio` (webhook de n8n, `ESCRITURA`) y `proponer_recargo` (`DINERO`). **`proponer_recargo` no puede ejecutarse todavía**: Gestión no publica la mutación `proponerRecargo` en `schema.graphql`; aprobarla termina `FALLIDA` con ese motivo (nunca se simula un recargo, F5). **No implementadas:** `aplicar_recargo`, `consultar_disponibilidad`, `crear_reserva`, `registrar_visita` (la regla G2 las menciona; no las exige la misión de referencia G1). `TODO(regla)`: definir con Aldana las mutaciones de recargos.
- **LLM:** `infrastructure/llm/groq.py` (API compatible con OpenAI y con llamadas a herramientas, vía `httpx`, sin SDK). El prompt del sistema está en `application/prompt_mision.py` y cita G1–G3 y F5. La misión se ejecuta con la cuenta de servicio de Keycloak (`condohub-servicios`) para leer Gestión.
- **Servidor MCP** (requisito «protocolo MCP»): `python -m app.infrastructure.mcp_server` (stdio, SDK oficial `mcp` 2.x, `MCPServer`). Expone las 6 herramientas; las de lectura responden y **las dos de escritura crean una confirmación pendiente** (misión `LIBRE` sin bucle de LLM, `iniciada_por = mcp`) que el ADMIN aprueba por la API: el mismo candado. Para que la API vea esas confirmaciones hace falta `PERSISTENCIA=mongo` en ambos procesos.
- **Variables nuevas:** `GROQ_API_KEY`, `GROQ_MODELO` (`openai/gpt-oss-20b`), `GROQ_URL_BASE`, `MISION_LIMITE_PASOS` (15), `RECARGO_MENSUAL` (0.02), `N8N_WEBHOOK_RECORDATORIOS`; y las del monitoreo (Gestión, Keycloak, Mongo, `N8N_WEBHOOK_ALERTAS`).
- **n8n:** dos flujos nuevos en `infra/n8n/flows/`: **«Alertas del agente de monitoreo»** (`POST /webhook/agente-alertas` → correo al `ADMIN_EMAIL`) y **«Recordatorio pedido por el agente»** (`POST /webhook/agente-recordatorio` → busca al titular en Gestión y le envía el mensaje aprobado). Se cargan con `node infra/n8n/importar.mjs`.
- **Base de datos:** `db/mongo-init.js` ahora acepta ids `string` (uuid) en `misionId`/`confirmacionId` (además de ObjectId), y añade `id`, `conLlm`, `version` y `llamadaId` con índices únicos por `id`.
- **Cambios en tests existentes (autorizados por Luis el 18/10/2026):** `tests/test_roles.py` esperaba `501` para el ADMIN en los 4 endpoints del esqueleto. Ahora exige que el ADMIN llegue a la lógica (ni 401 ni 403; los demás roles siguen recibiendo 403) y que una misión inexistente sea 404. Nada más se tocó.
- **Verificado (18/10/2026):** 210 pruebas (con MongoDB, S3 y RabbitMQ del compose, incluidas las 12 de `tests/integracion`; sin Mongo se omiten esas 12), `ruff check` y `mypy` limpios. **Misión de punta a punta con el LLM REAL (Groq, `openai/gpt-oss-20b`)** sobre FastAPI y MongoDB reales (Gestión y n8n simulados, con datos inventados): el agente consultó los morosos, calculó los recargos (15.60 y 7.80, F5), pidió proponerlos y enviar recordatorios; el ADMIN rechazó los recargos y aprobó los recordatorios; cada uno llegó a n8n **una sola vez**, nada se ejecutó sin aprobación y el agente cerró con un resumen coherente (con planes de pago en cuotas, G1), en ~26 s y 8 pasos del LLM. Aprobar `proponer_recargo` termina `FALLIDA` con el motivo honesto y el agente lo ve. Misión y confirmaciones también probadas con un LLM simulado: residente 403, doble aprobación 409, rechazo sin ejecución. **Servidor MCP** probado como proceso por stdio con un cliente MCP real. **n8n real**: la alerta del monitoreo llegó como correo al ADMIN (Mailpit); el flujo de recordatorios falla limpio (HTTP 500) cuando Gestión o Keycloak no están.
- **Hallazgos de probar con el LLM real (ya corregidos):** (1) Groq devolvió **HTTP 429** (límite de uso) a la 7.ª llamada y la misión murió en `ERROR`: ahora `LLMGroq` reintenta 429 y 5xx hasta 4 veces, respetando `Retry-After` (tope 30 s); (2) tras un rechazo el modelo **insistía** con la misma acción: ahora, si el ADMIN ya rechazó una herramienta para esa unidad en la misión, no se vuelve a pedir su aprobación y el agente recibe «no insistas»; (3) el prompt pide no llamar `estado_de_cuenta` por cada moroso (ahorra pasos y tokens).
- **Verificado contra el Gestión, Keycloak y n8n REALES (18/10/2026, datos de demostración del perfil `dev`):** `GestionGraphQL` y la cuenta de servicio `condohub-servicios` funcionan (60 unidades morosas, 27 000,00 de deuda vencida, 2 pagos pendientes, `estadoDeCuenta` con variables GraphQL). **Misión completa con LLM real + Gestión real + n8n real:** el agente consultó las 2 unidades más morosas, calculó el recargo (540,00 → 10,80), pidió proponerlo (el ADMIN lo rechazó) y enviar recordatorios con un plan de pago en dos cuotas (el ADMIN los aprobó): los dos correos llegaron a los buzones de los propietarios (`b101@…`, `b102@…`, Mailpit) pasando por el flujo «Recordatorio pedido por el agente», el gateway y Gestión, con el pie «redactado por el agente y aprobado por el administrador». Misión de 7 pasos del LLM en ~15 s. **Agente de monitoreo con datos reales:** detectó una anomalía verdadera (2 pagos `PENDIENTE` sin conciliar desde hace 5 días) y el aviso llegó por correo al ADMIN. En Gestión real el `unidadId` es un UUID y el `codigo` es `B-101`; el flujo de n8n acepta ambos.
- **Observación del monitoreo:** mientras una anomalía persiste, **cada ejecución diaria vuelve a avisarla** (misma alerta, mismo correo). Es coherente con «sigue sin resolverse», pero puede cansar al ADMIN; si molesta, habría que avisar solo cuando la alerta aparece o empeora (decisión de regla G5, pendiente).
- **No verificado:** la consola del ADMIN (Angular, de Aldana) que debe mostrar y aprobar las confirmaciones; el comportamiento del LLM con muchas más unidades o con datos reales de un condominio; `proponer_recargo` hasta que Gestión publique la mutación; el servidor MCP conectado a Gestión real (se probó por stdio y con dobles).

## Código funcional protegido (obligatorio)

Código en `main` con tests en verde **no se reescribe, refactoriza, renombra ni reformatea** si la tarea no lo pide explícitamente. Lo nuevo se agrega extendiendo (clases, métodos o archivos nuevos). Si es inevitable tocar código funcional, **detente antes de editar**, explica qué archivo/líneas y por qué, y espera confirmación; luego haz el mínimo diff. Nunca edites tests existentes para que pase código nuevo. Corre los tests antes y después: todo lo que pasaba debe seguir pasando. En el resumen, lista cada archivo existente que modificaste.
