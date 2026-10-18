"""Monitoreo del negocio (G5): métricas, anomalías, alertas e informes. Dominio puro: sin frameworks.

El agente **observa y avisa, nunca actúa** (G5, F5, G2): aquí solo hay datos y reglas de comparación.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

CIEN = Decimal(100)


class Severidad(StrEnum):
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class TipoAnomalia(StrEnum):
    MOROSIDAD_CRECIENTE = "MOROSIDAD_CRECIENTE"
    DEUDA_VENCIDA_CRECIENTE = "DEUDA_VENCIDA_CRECIENTE"
    PAGOS_SIN_CONCILIAR = "PAGOS_SIN_CONCILIAR"


class Origen(StrEnum):
    PROGRAMADO = "PROGRAMADO"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class Metricas:
    """Una lectura del estado del condominio (F4, F8). El dinero es `Decimal` (F10)."""

    generadas_en: datetime
    unidades_morosas: int
    deuda_vencida: Decimal
    pagos_pendientes: int
    dias_pago_mas_antiguo: int | None = None

    def __post_init__(self) -> None:
        if self.unidades_morosas < 0 or self.pagos_pendientes < 0:
            raise ValueError("Los conteos no pueden ser negativos")
        if self.deuda_vencida < 0:
            raise ValueError("La deuda vencida no puede ser negativa")
        if self.dias_pago_mas_antiguo is not None and self.dias_pago_mas_antiguo < 0:
            raise ValueError("Los días del pago más antiguo no pueden ser negativos")


@dataclass(frozen=True)
class Parametros:
    """Umbrales de G5. Son parámetros de negocio: vienen de la configuración, no del código."""

    ventana_historica: int = 3
    aumento_morosidad: Decimal = Decimal("0.20")
    aumento_minimo_unidades: int = 2
    aumento_deuda: Decimal = Decimal("0.20")
    pagos_pendientes_max: int = 5
    dias_pago_pendiente_max: int = 3
    factor_alta: int = 2

    def __post_init__(self) -> None:
        if self.ventana_historica < 1 or self.factor_alta < 2:
            raise ValueError("La ventana debe ser ≥ 1 y el factor de severidad alta ≥ 2")
        if self.aumento_morosidad <= 0 or self.aumento_deuda <= 0:
            raise ValueError("Los umbrales de aumento deben ser positivos")


@dataclass(frozen=True)
class Alerta:
    tipo: TipoAnomalia
    severidad: Severidad
    mensaje: str
    valor: str
    referencia: str


@dataclass(frozen=True)
class Informe:
    """Resultado de una ejecución del agente de monitoreo (agregado `InformeMonitoreo`)."""

    id: UUID
    generado_en: datetime
    origen: Origen
    metricas: Metricas
    alertas: tuple[Alerta, ...]
    resumen: str
    linea_base: bool = False
    notificado: bool = False

    @classmethod
    def nuevo(
        cls,
        generado_en: datetime,
        origen: Origen,
        metricas: Metricas,
        alertas: tuple[Alerta, ...],
        resumen: str,
        linea_base: bool,
    ) -> "Informe":
        return cls(uuid4(), generado_en, origen, metricas, alertas, resumen, linea_base)

    def marcar_notificado(self) -> "Informe":
        return Informe(
            self.id,
            self.generado_en,
            self.origen,
            self.metricas,
            self.alertas,
            self.resumen,
            self.linea_base,
            True,
        )


def _promedio(valores: Sequence[Decimal]) -> Decimal:
    return sum(valores, Decimal(0)) / len(valores)


def _pct(valor: Decimal) -> str:
    return f"{(valor * CIEN).quantize(Decimal('0.1'))} %"


class DetectorAnomalias:
    """Servicio de dominio de G5: compara la lectura actual con el promedio de las anteriores."""

    @staticmethod
    def evaluar(actual: Metricas, historico: Sequence[Metricas], p: Parametros) -> tuple[Alerta, ...]:
        """`historico`: lecturas anteriores (sin la actual). Sin historia solo se evalúan los pagos."""
        recientes = list(historico)[-p.ventana_historica :]
        alertas: list[Alerta] = []
        if recientes:
            alertas += DetectorAnomalias._morosidad(actual, recientes, p)
            alertas += DetectorAnomalias._deuda(actual, recientes, p)
        alertas += DetectorAnomalias._pagos(actual, p)
        return tuple(alertas)

    @staticmethod
    def _morosidad(actual: Metricas, recientes: Sequence[Metricas], p: Parametros) -> list[Alerta]:
        base = _promedio([Decimal(m.unidades_morosas) for m in recientes])
        subida = Decimal(actual.unidades_morosas) - base
        if subida < p.aumento_minimo_unidades or Decimal(actual.unidades_morosas) < base * (
            1 + p.aumento_morosidad
        ):
            return []
        severa = Decimal(actual.unidades_morosas) >= base * (1 + p.aumento_morosidad * p.factor_alta)
        return [
            Alerta(
                TipoAnomalia.MOROSIDAD_CRECIENTE,
                Severidad.ALTA if severa else Severidad.MEDIA,
                f"Las unidades morosas subieron de {base.quantize(Decimal('0.1'))} (promedio anterior) "
                f"a {actual.unidades_morosas}.",
                str(actual.unidades_morosas),
                str(base.quantize(Decimal("0.1"))),
            )
        ]

    @staticmethod
    def _deuda(actual: Metricas, recientes: Sequence[Metricas], p: Parametros) -> list[Alerta]:
        base = _promedio([m.deuda_vencida for m in recientes])
        if base <= 0 or actual.deuda_vencida < base * (1 + p.aumento_deuda):
            return []
        aumento = actual.deuda_vencida / base - 1
        severa = actual.deuda_vencida >= base * (1 + p.aumento_deuda * p.factor_alta)
        return [
            Alerta(
                TipoAnomalia.DEUDA_VENCIDA_CRECIENTE,
                Severidad.ALTA if severa else Severidad.MEDIA,
                f"La deuda vencida subió {_pct(aumento)} respecto del promedio anterior "
                f"({base.quantize(Decimal('0.01'))} → {actual.deuda_vencida.quantize(Decimal('0.01'))}).",
                str(actual.deuda_vencida.quantize(Decimal("0.01"))),
                str(base.quantize(Decimal("0.01"))),
            )
        ]

    @staticmethod
    def _pagos(actual: Metricas, p: Parametros) -> list[Alerta]:
        por_cantidad = actual.pagos_pendientes >= p.pagos_pendientes_max
        dias = actual.dias_pago_mas_antiguo or 0
        por_antiguedad = actual.pagos_pendientes > 0 and dias >= p.dias_pago_pendiente_max
        if not (por_cantidad or por_antiguedad):
            return []
        severa = actual.pagos_pendientes >= p.pagos_pendientes_max * p.factor_alta or (
            por_antiguedad and dias >= p.dias_pago_pendiente_max * p.factor_alta
        )
        return [
            Alerta(
                TipoAnomalia.PAGOS_SIN_CONCILIAR,
                Severidad.ALTA if severa else Severidad.MEDIA,
                f"Hay {actual.pagos_pendientes} pagos PENDIENTE de conciliar"
                + (
                    f"; el más antiguo lleva {dias} días."
                    if actual.dias_pago_mas_antiguo is not None
                    else "."
                ),
                str(actual.pagos_pendientes),
                str(p.pagos_pendientes_max),
            )
        ]
