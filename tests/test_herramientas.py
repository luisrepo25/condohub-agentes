"""Catálogo de herramientas (habilidades del agente): lecturas, cálculo de recargo (F5) y validación de
argumentos."""

from decimal import Decimal

import pytest

from app.application.herramientas import AccionNoDisponible, CatalogoCondohub
from app.domain.mision import Riesgo
from tests.dobles_mision import Mundo, RecargosFalsos


@pytest.fixture()
def catalogo() -> CatalogoCondohub:
    return Mundo().catalogo


def test_G2_las_herramientas_de_escritura_y_dinero_estan_marcadas(catalogo: CatalogoCondohub) -> None:
    riesgos = {h.nombre: h.riesgo for h in catalogo.listar()}
    assert riesgos["proponer_recargo"] is Riesgo.DINERO
    assert riesgos["enviar_recordatorio"] is Riesgo.ESCRITURA
    assert {n for n, r in riesgos.items() if r is Riesgo.LECTURA} == {
        "consultar_morosos",
        "estado_de_cuenta",
        "pagos_pendientes",
        "calcular_recargo",
    }


def test_G2_cada_herramienta_declara_su_esquema_json(catalogo: CatalogoCondohub) -> None:
    for h in catalogo.listar():
        assert h.parametros["type"] == "object" and h.parametros["additionalProperties"] is False


def test_F4_consultar_morosos_ordena_por_deuda_y_suma_el_total(catalogo: CatalogoCondohub) -> None:
    r = catalogo.ejecutar("consultar_morosos", {})
    assert [u["unidadId"] for u in r["unidades"]] == ["u1", "u2"]
    assert r["total"] == 2 and r["deudaVencidaTotal"] == "510.50"  # F10: strings decimales


def test_F4_consultar_morosos_respeta_el_limite(catalogo: CatalogoCondohub) -> None:
    assert len(catalogo.ejecutar("consultar_morosos", {"limite": 1})["unidades"]) == 1


@pytest.mark.parametrize("limite", [0, 51, "5", True, 2.5])
def test_G2_un_limite_invalido_se_rechaza(catalogo: CatalogoCondohub, limite: object) -> None:
    with pytest.raises(ValueError):
        catalogo.ejecutar("consultar_morosos", {"limite": limite})


def test_F1_estado_de_cuenta_de_una_unidad(catalogo: CatalogoCondohub) -> None:
    r = catalogo.ejecutar("estado_de_cuenta", {"unidadId": "u1"})
    assert r["deudaVencida"] == "390.00" and r["moroso"] is True and r["expensasVencidas"] == 2


def test_F8_pagos_pendientes_con_su_fecha(catalogo: CatalogoCondohub) -> None:
    r = catalogo.ejecutar("pagos_pendientes", {})
    assert r["total"] == 1 and r["pagos"][0]["fechaPago"] == "2026-10-19"


def test_F5_el_recargo_es_el_2_por_ciento_simple_mensual(catalogo: CatalogoCondohub) -> None:
    r = catalogo.ejecutar("calcular_recargo", {"deudaVencida": "390.00"})
    assert r["recargo"] == "7.80" and r["porcentajeMensual"] == "2.00" and "ADMIN" in r["nota"]


def test_F5_el_recargo_simple_crece_linealmente_con_los_meses(catalogo: CatalogoCondohub) -> None:
    assert catalogo.ejecutar("calcular_recargo", {"deudaVencida": "390.00", "meses": 3})["recargo"] == "23.40"


def test_F10_el_recargo_se_redondea_a_2_decimales_hacia_arriba_en_el_medio(
    catalogo: CatalogoCondohub,
) -> None:
    assert (
        catalogo.ejecutar("calcular_recargo", {"deudaVencida": "0.25"})["recargo"] == "0.01"
    )  # 0.005 → 0.01


def test_F5_el_porcentaje_sale_del_parametro_no_del_codigo() -> None:
    mundo = Mundo()
    catalogo = CatalogoCondohub(mundo.gestion, mundo.recordatorios, mundo.recargos, Decimal("0.05"))
    assert catalogo.ejecutar("calcular_recargo", {"deudaVencida": "100.00"})["recargo"] == "5.00"


@pytest.mark.parametrize("deuda", ["abc", "-1", "NaN", "Infinity", 100, None])
def test_F10_el_dinero_debe_ser_un_string_decimal_valido(catalogo: CatalogoCondohub, deuda: object) -> None:
    with pytest.raises(ValueError):
        catalogo.ejecutar("calcular_recargo", {"deudaVencida": deuda})


def test_F5_proponer_recargo_valida_sin_ejecutar_nada() -> None:
    mundo = Mundo()
    mundo.catalogo.validar("proponer_recargo", {"unidadId": "u1", "monto": "7.80", "motivo": "Mora de 1 mes"})
    assert mundo.recargos.propuestos == []


@pytest.mark.parametrize(
    "argumentos",
    [
        {"unidadId": "u1", "monto": "0", "motivo": "x"},
        {"unidadId": "u1", "monto": "7.80", "motivo": ""},
        {"unidadId": "", "monto": "7.80", "motivo": "x"},
        {"monto": "7.80", "motivo": "x"},
    ],
)
def test_F5_proponer_recargo_rechaza_argumentos_invalidos(
    catalogo: CatalogoCondohub, argumentos: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        catalogo.validar("proponer_recargo", argumentos)


def test_G2_enviar_recordatorio_llega_a_n8n_solo_al_ejecutarse() -> None:
    mundo = Mundo()
    mundo.catalogo.validar("enviar_recordatorio", {"unidadId": "u1", "mensaje": "Hola"})
    assert mundo.recordatorios.enviados == []
    mundo.catalogo.ejecutar("enviar_recordatorio", {"unidadId": "u1", "mensaje": "Hola"})
    assert mundo.recordatorios.enviados == [("u1", "Hola")]


def test_G2_una_herramienta_desconocida_no_se_ejecuta(catalogo: CatalogoCondohub) -> None:
    assert catalogo.obtener("borrar_todo") is None
    with pytest.raises(ValueError):
        catalogo.ejecutar("borrar_todo", {})
    with pytest.raises(ValueError):
        catalogo.validar("borrar_todo", {})


def test_F5_si_la_accion_no_esta_disponible_se_propaga() -> None:
    mundo = Mundo(recargos=RecargosFalsos(falla=True))
    with pytest.raises(AccionNoDisponible):
        mundo.catalogo.ejecutar("proponer_recargo", {"unidadId": "u1", "monto": "7.80", "motivo": "x"})
