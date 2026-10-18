"""G5: el agente de monitoreo compara la lectura actual con las anteriores y avisa; nunca actúa."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.monitoreo import DetectorAnomalias, Metricas, Parametros, Severidad, TipoAnomalia

P = Parametros()
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def lectura(
    dia: int = 0, morosas: int = 10, deuda: str = "1000.00", pagos: int = 0, antiguo: int | None = None
) -> Metricas:
    return Metricas(T0 + timedelta(days=dia), morosas, Decimal(deuda), pagos, antiguo)


def historia(morosas: int = 10, deuda: str = "1000.00") -> list[Metricas]:
    return [lectura(i, morosas, deuda) for i in range(3)]


def tipos(alertas: tuple) -> set[TipoAnomalia]:  # type: ignore[type-arg]
    return {a.tipo for a in alertas}


def test_G5_sin_cambios_no_hay_alertas() -> None:
    assert DetectorAnomalias.evaluar(lectura(5), historia(), P) == ()


def test_G5_morosidad_que_sube_20_por_ciento_y_2_unidades_genera_alerta_media() -> None:
    alertas = DetectorAnomalias.evaluar(lectura(5, morosas=12), historia(10), P)
    assert tipos(alertas) == {TipoAnomalia.MOROSIDAD_CRECIENTE}
    assert alertas[0].severidad is Severidad.MEDIA


def test_G5_morosidad_que_sube_el_doble_del_umbral_es_alta() -> None:
    alertas = DetectorAnomalias.evaluar(lectura(5, morosas=14), historia(10), P)
    assert alertas[0].severidad is Severidad.ALTA


def test_G5_una_subida_de_una_sola_unidad_no_alerta_aunque_supere_el_porcentaje() -> None:
    assert DetectorAnomalias.evaluar(lectura(5, morosas=3), historia(2), P) == ()


def test_G5_deuda_vencida_que_sube_20_por_ciento_genera_alerta() -> None:
    alertas = DetectorAnomalias.evaluar(lectura(5, deuda="1200.00"), historia(), P)
    assert tipos(alertas) == {TipoAnomalia.DEUDA_VENCIDA_CRECIENTE}
    assert alertas[0].severidad is Severidad.MEDIA
    assert alertas[0].valor == "1200.00" and alertas[0].referencia == "1000.00"


def test_G5_deuda_vencida_que_sube_40_por_ciento_es_alta() -> None:
    assert (
        DetectorAnomalias.evaluar(lectura(5, deuda="1400.00"), historia(), P)[0].severidad is Severidad.ALTA
    )


def test_G5_deuda_que_baja_no_alerta() -> None:
    assert DetectorAnomalias.evaluar(lectura(5, morosas=4, deuda="400.00"), historia(), P) == ()


def test_G5_pagos_pendientes_en_cantidad_alertan_aunque_no_haya_historia() -> None:
    alertas = DetectorAnomalias.evaluar(lectura(0, pagos=5, antiguo=0), [], P)
    assert tipos(alertas) == {TipoAnomalia.PAGOS_SIN_CONCILIAR}
    assert alertas[0].severidad is Severidad.MEDIA


def test_G5_un_pago_pendiente_con_3_dias_alerta() -> None:
    assert tipos(DetectorAnomalias.evaluar(lectura(0, pagos=1, antiguo=3), [], P)) == {
        TipoAnomalia.PAGOS_SIN_CONCILIAR
    }


def test_G5_un_pago_pendiente_reciente_no_alerta() -> None:
    assert DetectorAnomalias.evaluar(lectura(0, pagos=1, antiguo=2), [], P) == ()


def test_G5_pagos_el_doble_del_umbral_es_alta() -> None:
    assert DetectorAnomalias.evaluar(lectura(0, pagos=10, antiguo=0), [], P)[0].severidad is Severidad.ALTA


def test_G5_sin_historia_solo_se_evaluan_los_pagos() -> None:
    assert DetectorAnomalias.evaluar(lectura(0, morosas=50, deuda="99999.00"), [], P) == ()


def test_G5_solo_cuenta_la_ventana_de_las_ultimas_lecturas() -> None:
    antiguas = [lectura(i, morosas=100) for i in range(5)]  # fuera de la ventana de 3
    recientes = [lectura(10 + i, morosas=10) for i in range(3)]
    assert DetectorAnomalias.evaluar(lectura(20, morosas=10), antiguas + recientes, P) == ()


def test_G5_pueden_saltar_varias_alertas_a_la_vez() -> None:
    alertas = DetectorAnomalias.evaluar(
        lectura(5, morosas=14, deuda="1400.00", pagos=6, antiguo=1), historia(), P
    )
    assert tipos(alertas) == set(TipoAnomalia)


@pytest.mark.parametrize("campo", ["unidades_morosas", "pagos_pendientes"])
def test_F10_las_metricas_no_admiten_conteos_negativos(campo: str) -> None:
    kwargs = {"unidades_morosas": 0, "pagos_pendientes": 0, campo: -1}
    with pytest.raises(ValueError):
        Metricas(T0, deuda_vencida=Decimal(0), **kwargs)  # type: ignore[arg-type]


def test_F10_la_deuda_vencida_no_puede_ser_negativa() -> None:
    with pytest.raises(ValueError):
        Metricas(T0, 0, Decimal("-0.01"), 0)


def test_G5_los_parametros_se_validan() -> None:
    with pytest.raises(ValueError):
        Parametros(ventana_historica=0)
    with pytest.raises(ValueError):
        Parametros(aumento_morosidad=Decimal(0))
