"""El agente conoce la fecha de hoy: sin ella el LLM inventa el día y el mes (fallo visto en producción)."""

from datetime import UTC, datetime

from app.application.fecha_actual import sistema_con_fecha

BASE = "Eres el agente de CondoHub."


def test_G1_el_prompt_incluye_la_fecha_y_el_dia_de_la_semana() -> None:
    texto = sistema_con_fecha(BASE, datetime(2026, 11, 6, 15, 30, tzinfo=UTC))

    assert texto.startswith(BASE)
    assert "viernes 2026-11-06" in texto


def test_G1_el_dia_de_la_semana_es_el_de_la_fecha_y_no_el_de_otro_dia() -> None:
    sabado = sistema_con_fecha(BASE, datetime(2026, 11, 7, 0, 0, tzinfo=UTC))
    lunes = sistema_con_fecha(BASE, datetime(2026, 11, 9, 0, 0, tzinfo=UTC))

    assert "sábado 2026-11-07" in sabado
    assert "lunes 2026-11-09" in lunes


def test_G1_el_prompt_original_no_se_modifica() -> None:
    sistema_con_fecha(BASE, datetime(2026, 11, 6, tzinfo=UTC))

    assert BASE == "Eres el agente de CondoHub."
