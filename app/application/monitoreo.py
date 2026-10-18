"""Agente de monitoreo (G5): leer, comparar, informar y avisar. Nunca modifica nada del negocio."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from app.domain.monitoreo import Alerta, DetectorAnomalias, Informe, Metricas, Origen, Parametros


class GestionNoDisponible(Exception):
    """Gestión no responde, rechazó la cuenta de servicio o devolvió datos inesperados."""


class NotificacionFallida(Exception):
    """No se pudo avisar al ADMIN (n8n caído o sin configurar). El informe se guarda igual."""


@dataclass(frozen=True)
class MorosoDato:
    unidad_id: str
    deuda_vencida: Decimal
    expensas_vencidas: int


@dataclass(frozen=True)
class PagoPendienteDato:
    id: str
    monto: Decimal
    fecha_pago: date


class GestionPort(Protocol):
    """Habilidades de solo lectura del agente sobre Finanzas (contrato GraphQL de Gestión)."""

    def morosos(self) -> list[MorosoDato]: ...

    def pagos_pendientes(self) -> list[PagoPendienteDato]: ...


class MetricasRepository(Protocol):
    def guardar(self, metricas: Metricas) -> None: ...

    def ultimas(self, cantidad: int) -> list[Metricas]:
        """Las últimas lecturas, de la más antigua a la más reciente."""
        ...


class InformeRepository(Protocol):
    def guardar(self, informe: Informe) -> None: ...

    def ultimos(self, cantidad: int) -> list[Informe]:
        """Del más reciente al más antiguo."""
        ...


class Notificador(Protocol):
    def avisar(self, informe: Informe) -> None:
        """Lanza `NotificacionFallida` si no pudo avisar."""
        ...


class Reloj(Protocol):
    def ahora(self) -> datetime: ...


def redactar_resumen(metricas: Metricas, alertas: tuple[Alerta, ...], linea_base: bool) -> str:
    """Resumen en lenguaje natural del informe (plantilla fija: no depende de ningún LLM)."""
    partes = [
        f"{metricas.unidades_morosas} unidades morosas, deuda vencida {metricas.deuda_vencida:.2f} "
        f"y {metricas.pagos_pendientes} pagos PENDIENTE de conciliar."
    ]
    if linea_base:
        partes.append("Primera lectura: se usa como línea base; solo se evalúan los pagos sin conciliar.")
    if not alertas:
        partes.append("Sin alertas.")
    else:
        partes.append(
            f"{len(alertas)} alerta(s): " + " ".join(f"[{a.severidad}] {a.mensaje}" for a in alertas)
        )
    return " ".join(partes)


class EjecutarMonitoreo:
    def __init__(
        self,
        gestion: GestionPort,
        metricas: MetricasRepository,
        informes: InformeRepository,
        notificador: Notificador,
        reloj: Reloj,
        parametros: Parametros,
    ) -> None:
        self._gestion = gestion
        self._metricas = metricas
        self._informes = informes
        self._notificador = notificador
        self._reloj = reloj
        self._p = parametros

    def ejecutar(self, origen: Origen) -> Informe:
        ahora = self._reloj.ahora()
        morosos = self._gestion.morosos()  # si Gestión falla no se guarda nada
        pagos = self._gestion.pagos_pendientes()
        dias = max(((ahora.date() - p.fecha_pago).days for p in pagos), default=None)
        actual = Metricas(
            generadas_en=ahora,
            unidades_morosas=len(morosos),
            deuda_vencida=sum((m.deuda_vencida for m in morosos), Decimal(0)),
            pagos_pendientes=len(pagos),
            dias_pago_mas_antiguo=None if dias is None else max(0, dias),
        )
        historico = self._metricas.ultimas(self._p.ventana_historica)
        alertas = DetectorAnomalias.evaluar(actual, historico, self._p)
        informe = Informe.nuevo(
            ahora, origen, actual, alertas, redactar_resumen(actual, alertas, not historico), not historico
        )
        if alertas:
            try:
                self._notificador.avisar(informe)
                informe = informe.marcar_notificado()
            except NotificacionFallida:
                pass
        self._metricas.guardar(actual)
        self._informes.guardar(informe)
        return informe


class ListarInformes:
    def __init__(self, informes: InformeRepository) -> None:
        self._informes = informes

    def listar(self, limite: int) -> list[Informe]:
        return self._informes.ultimos(limite)
