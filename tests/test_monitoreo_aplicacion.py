"""Caso de uso del agente de monitoreo (G5) con dobles en memoria: sin red ni base de datos."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.application.monitoreo import (
    EjecutarMonitoreo,
    GestionNoDisponible,
    ListarInformes,
    MorosoDato,
    NotificacionFallida,
    PagoPendienteDato,
)
from app.domain.monitoreo import Informe, Metricas, Origen, Parametros, TipoAnomalia
from app.infrastructure.memoria import InformesEnMemoria, MetricasEnMemoria

AHORA = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


class GestionFalsa:
    def __init__(
        self, morosos: list[MorosoDato] | None = None, pagos: list[PagoPendienteDato] | None = None
    ) -> None:
        self.morosos_ = morosos or []
        self.pagos_ = pagos or []
        self.caida = False

    def morosos(self) -> list[MorosoDato]:
        if self.caida:
            raise GestionNoDisponible("Gestión caída")
        return self.morosos_

    def pagos_pendientes(self) -> list[PagoPendienteDato]:
        return self.pagos_


class NotificadorFalso:
    def __init__(self, falla: bool = False) -> None:
        self.avisos: list[Informe] = []
        self.falla = falla

    def avisar(self, informe: Informe) -> None:
        if self.falla:
            raise NotificacionFallida("n8n caído")
        self.avisos.append(informe)


class RelojFijo:
    def ahora(self) -> datetime:
        return AHORA


def moroso(i: int, deuda: str = "100.00") -> MorosoDato:
    return MorosoDato(f"U{i}", Decimal(deuda), 1)


def armar(gestion: GestionFalsa, notificador: NotificadorFalso | None = None):  # type: ignore[no-untyped-def]
    metricas, informes = MetricasEnMemoria(), InformesEnMemoria()
    noti = notificador or NotificadorFalso()
    return (
        EjecutarMonitoreo(gestion, metricas, informes, noti, RelojFijo(), Parametros()),
        metricas,
        informes,
        noti,
    )


def test_G5_la_primera_lectura_es_linea_base_y_no_alerta_por_morosidad() -> None:
    caso, metricas, informes, noti = armar(GestionFalsa([moroso(i) for i in range(30)]))
    informe = caso.ejecutar(Origen.MANUAL)
    assert informe.linea_base and informe.alertas == () and noti.avisos == []
    assert informe.metricas.unidades_morosas == 30 and informe.metricas.deuda_vencida == Decimal("3000.00")
    assert len(metricas.ultimas(5)) == 1 and len(informes.ultimos(5)) == 1


def test_G5_una_subida_de_morosidad_genera_alerta_y_avisa_al_admin() -> None:
    caso, metricas, _, noti = armar(GestionFalsa([moroso(i) for i in range(20)]))
    for _ in range(3):
        metricas.guardar(Metricas(AHORA, 10, Decimal("1000.00"), 0))
    informe = caso.ejecutar(Origen.PROGRAMADO)
    assert TipoAnomalia.MOROSIDAD_CRECIENTE in {a.tipo for a in informe.alertas}
    assert informe.notificado and [i.id for i in noti.avisos] == [informe.id]
    assert "alerta" in informe.resumen


def test_G5_si_n8n_falla_el_informe_se_guarda_igual_sin_marcar_notificado() -> None:
    caso, metricas, informes, _ = armar(
        GestionFalsa(pagos=[PagoPendienteDato(f"P{i}", Decimal(10), date(2026, 10, 20)) for i in range(6)]),
        NotificadorFalso(falla=True),
    )
    informe = caso.ejecutar(Origen.MANUAL)
    assert informe.alertas and not informe.notificado
    assert informes.ultimos(1)[0].id == informe.id


def test_G5_sin_alertas_no_se_avisa() -> None:
    caso, _, _, noti = armar(GestionFalsa())
    caso.ejecutar(Origen.MANUAL)
    assert noti.avisos == []


def test_F8_los_dias_del_pago_mas_antiguo_salen_de_la_fecha_del_comprobante() -> None:
    pagos = [
        PagoPendienteDato("A", Decimal(1), date(2026, 10, 17)),
        PagoPendienteDato("B", Decimal(1), date(2026, 10, 19)),
    ]
    caso, *_ = armar(GestionFalsa(pagos=pagos))
    assert caso.ejecutar(Origen.MANUAL).metricas.dias_pago_mas_antiguo == 3


def test_G5_si_gestion_no_responde_no_se_guarda_nada() -> None:
    gestion = GestionFalsa()
    gestion.caida = True
    caso, metricas, informes, _ = armar(gestion)
    with pytest.raises(GestionNoDisponible):
        caso.ejecutar(Origen.MANUAL)
    assert metricas.ultimas(5) == [] and informes.ultimos(5) == []


def test_G5_los_informes_se_listan_del_mas_reciente_al_mas_antiguo() -> None:
    caso, _, informes, _ = armar(GestionFalsa())
    primero, segundo = caso.ejecutar(Origen.MANUAL), caso.ejecutar(Origen.MANUAL)
    assert [i.id for i in ListarInformes(informes).listar(10)] == [segundo.id, primero.id]
    assert len(ListarInformes(informes).listar(1)) == 1
