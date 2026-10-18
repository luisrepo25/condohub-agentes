"""Habilidades del agente (herramientas MCP). El LLM solo actúa a través de este catálogo (G2).

Las de lectura se ejecutan al instante; las de escritura o dinero las gobierna `application/mision.py`: no
se ejecutan
hasta que un ADMIN las aprueba. Nada de aquí crea cargos por sí solo (F5): `proponer_recargo` solo registra
una propuesta.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol

from app.application.monitoreo import MorosoDato, PagoPendienteDato
from app.domain.mision import Riesgo

CENTAVOS = Decimal("0.01")


class AccionNoDisponible(Exception):
    """La acción no puede ejecutarse (falta configuración o el servicio destino no existe todavía)."""


@dataclass(frozen=True)
class EstadoCuentaDato:
    unidad_id: str
    codigo: str
    bloque: str
    deuda_total: Decimal
    deuda_vencida: Decimal
    expensas_vencidas: int
    saldo_a_favor: Decimal
    moroso: bool


class GestionLectura(Protocol):
    """Lecturas de Finanzas por GraphQL (solo `query`)."""

    def morosos(self) -> list[MorosoDato]: ...

    def pagos_pendientes(self) -> list[PagoPendienteDato]: ...

    def estado_de_cuenta(self, unidad_id: str) -> EstadoCuentaDato: ...


class Recordatorios(Protocol):
    def enviar(self, unidad_id: str, mensaje: str) -> dict[str, Any]: ...


class Recargos(Protocol):
    def proponer(self, unidad_id: str, monto: Decimal, motivo: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    parametros: dict[str, Any]  # JSON Schema del objeto de argumentos
    riesgo: Riesgo


class CatalogoHerramientas(Protocol):
    def listar(self) -> list[Herramienta]: ...

    def obtener(self, nombre: str) -> Herramienta | None: ...

    def validar(self, nombre: str, argumentos: dict[str, Any]) -> None:
        """Lanza `ValueError` si los argumentos no sirven; no ejecuta nada."""
        ...

    def ejecutar(self, nombre: str, argumentos: dict[str, Any]) -> dict[str, Any]: ...


def _objeto(propiedades: dict[str, Any], requeridas: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": propiedades,
        "required": requeridas,
        "additionalProperties": False,
    }


_UNIDAD = {"type": "string", "description": "Identificador de la unidad (unidadId de Gestión)"}

HERRAMIENTAS = (
    Herramienta(
        "consultar_morosos",
        "Lista las unidades morosas (con al menos un cargo vencido e impago), de mayor a menor deuda "
        "vencida.",
        _objeto({"limite": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}}, []),
        Riesgo.LECTURA,
    ),
    Herramienta(
        "estado_de_cuenta",
        "Estado de cuenta de una unidad: deuda total y vencida, expensas vencidas, saldo a favor.",
        _objeto({"unidadId": _UNIDAD}, ["unidadId"]),
        Riesgo.LECTURA,
    ),
    Herramienta(
        "pagos_pendientes",
        "Pagos en estado PENDIENTE a la espera de conciliación (F8).",
        _objeto({}, []),
        Riesgo.LECTURA,
    ),
    Herramienta(
        "calcular_recargo",
        "Calcula el recargo por mora (interés simple mensual, F5) sobre una deuda vencida. Solo calcula: "
        "no lo aplica.",
        _objeto(
            {
                "deudaVencida": {"type": "string", "description": 'Dinero como string decimal, ej. "390.00"'},
                "meses": {"type": "integer", "minimum": 1, "maximum": 24, "default": 1},
            },
            ["deudaVencida"],
        ),
        Riesgo.LECTURA,
    ),
    Herramienta(
        "proponer_recargo",
        "Registra una propuesta de recargo por mora para una unidad. Requiere confirmación del ADMIN (F5, "
        "G2).",
        _objeto(
            {
                "unidadId": _UNIDAD,
                "monto": {"type": "string", "description": "Dinero como string decimal, mayor que 0"},
                "motivo": {"type": "string", "description": "Por qué se propone (ej. mora de 1 mes)"},
            },
            ["unidadId", "monto", "motivo"],
        ),
        Riesgo.DINERO,
    ),
    Herramienta(
        "enviar_recordatorio",
        "Envía un recordatorio de pago al propietario titular de la unidad por n8n. Requiere confirmación "
        "del ADMIN.",
        _objeto(
            {"unidadId": _UNIDAD, "mensaje": {"type": "string", "maxLength": 1000}}, ["unidadId", "mensaje"]
        ),
        Riesgo.ESCRITURA,
    ),
)


def _texto(argumentos: dict[str, Any], clave: str, maximo: int = 1000) -> str:
    valor = argumentos.get(clave)
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"«{clave}» es obligatorio y debe ser texto")
    if len(valor) > maximo:
        raise ValueError(f"«{clave}» no puede pasar de {maximo} caracteres")
    return valor.strip()


def _entero(argumentos: dict[str, Any], clave: str, defecto: int, minimo: int, maximo: int) -> int:
    valor = argumentos.get(clave, defecto)
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise ValueError(f"«{clave}» debe ser un entero entre {minimo} y {maximo}")
    return valor


def _dinero(argumentos: dict[str, Any], clave: str, permitir_cero: bool) -> Decimal:
    valor = argumentos.get(clave)
    try:
        monto = Decimal(valor) if isinstance(valor, str) else Decimal("NaN")
    except InvalidOperation:
        monto = Decimal("NaN")
    if monto.is_nan() or not monto.is_finite() or monto < 0 or (monto == 0 and not permitir_cero):
        raise ValueError(
            f'«{clave}» debe ser un string decimal {"≥" if permitir_cero else ">"} 0, ej. "390.00"'
        )
    return monto.quantize(CENTAVOS, ROUND_HALF_UP)


class CatalogoCondohub:
    """Catálogo real: lecturas de Gestión y las dos acciones (recordatorio y propuesta de recargo)."""

    def __init__(
        self,
        gestion: GestionLectura,
        recordatorios: Recordatorios,
        recargos: Recargos,
        recargo_mensual: Decimal,
    ) -> None:
        self._gestion = gestion
        self._recordatorios = recordatorios
        self._recargos = recargos
        self._recargo_mensual = recargo_mensual
        self._por_nombre = {h.nombre: h for h in HERRAMIENTAS}

    def listar(self) -> list[Herramienta]:
        return list(HERRAMIENTAS)

    def obtener(self, nombre: str) -> Herramienta | None:
        return self._por_nombre.get(nombre)

    def validar(self, nombre: str, argumentos: dict[str, Any]) -> None:
        if nombre not in self._por_nombre:
            raise ValueError(f"Herramienta desconocida: {nombre}")
        if nombre == "proponer_recargo":
            (
                _texto(argumentos, "unidadId", 100),
                _dinero(argumentos, "monto", False),
                _texto(argumentos, "motivo", 300),
            )
        elif nombre == "enviar_recordatorio":
            _texto(argumentos, "unidadId", 100), _texto(argumentos, "mensaje", 1000)

    def ejecutar(self, nombre: str, argumentos: dict[str, Any]) -> dict[str, Any]:
        if nombre not in self._por_nombre:
            raise ValueError(f"Herramienta desconocida: {nombre}")
        return getattr(self, f"_{nombre}")(argumentos)  # type: ignore[no-any-return]

    def _consultar_morosos(self, a: dict[str, Any]) -> dict[str, Any]:
        limite = _entero(a, "limite", 20, 1, 50)
        morosos = sorted(self._gestion.morosos(), key=lambda m: m.deuda_vencida, reverse=True)
        return {
            "total": len(morosos),
            "deudaVencidaTotal": f"{sum((m.deuda_vencida for m in morosos), Decimal(0)):.2f}",
            "unidades": [
                {
                    "unidadId": m.unidad_id,
                    "deudaVencida": f"{m.deuda_vencida:.2f}",
                    "expensasVencidas": m.expensas_vencidas,
                }
                for m in morosos[:limite]
            ],
        }

    def _estado_de_cuenta(self, a: dict[str, Any]) -> dict[str, Any]:
        e = self._gestion.estado_de_cuenta(_texto(a, "unidadId", 100))
        return {
            "unidadId": e.unidad_id,
            "codigo": e.codigo,
            "bloque": e.bloque,
            "deudaTotal": f"{e.deuda_total:.2f}",
            "deudaVencida": f"{e.deuda_vencida:.2f}",
            "expensasVencidas": e.expensas_vencidas,
            "saldoAFavor": f"{e.saldo_a_favor:.2f}",
            "moroso": e.moroso,
        }

    def _pagos_pendientes(self, _: dict[str, Any]) -> dict[str, Any]:
        pagos = self._gestion.pagos_pendientes()
        return {
            "total": len(pagos),
            "pagos": [
                {"id": p.id, "monto": f"{p.monto:.2f}", "fechaPago": p.fecha_pago.isoformat()}
                for p in pagos[:50]
            ],
        }

    def _calcular_recargo(self, a: dict[str, Any]) -> dict[str, Any]:
        deuda = _dinero(a, "deudaVencida", permitir_cero=True)
        meses = _entero(a, "meses", 1, 1, 24)
        return {
            "deudaVencida": f"{deuda:.2f}",
            "meses": meses,
            "porcentajeMensual": f"{self._recargo_mensual * 100:.2f}",
            "recargo": f"{(deuda * self._recargo_mensual * meses).quantize(CENTAVOS, ROUND_HALF_UP):.2f}",
            "nota": "Es una propuesta de cálculo: solo se aplica si el ADMIN lo confirma (F5).",
        }

    def _proponer_recargo(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._recargos.proponer(
            _texto(a, "unidadId", 100), _dinero(a, "monto", False), _texto(a, "motivo", 300)
        )

    def _enviar_recordatorio(self, a: dict[str, Any]) -> dict[str, Any]:
        return self._recordatorios.enviar(_texto(a, "unidadId", 100), _texto(a, "mensaje", 1000))
