"""Job programado del monitoreo (G5): salida segura en cualquier consola y código de salida según Gestión."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.application.monitoreo import GestionNoDisponible
from app.domain.monitoreo import Informe, Metricas, Origen
from app.jobs import monitorear


class _Ejecutar:
    def __init__(self, informe: Informe | None) -> None:
        self._informe = informe

    def ejecutar(self, origen: Origen) -> Informe:
        if self._informe is None:
            raise GestionNoDisponible("Gestión caída")
        return self._informe


class _Monitoreo:
    def __init__(self, informe: Informe | None) -> None:
        self.ejecutar = _Ejecutar(informe)


def _informe(resumen: str) -> Informe:
    ahora = datetime(2026, 10, 20, tzinfo=UTC)
    return Informe.nuevo(ahora, Origen.PROGRAMADO, Metricas(ahora, 1, Decimal("1.00"), 0), (), resumen, False)


def test_G5_la_salida_del_job_es_ascii_para_no_caerse_en_consolas_cp1252(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        monitorear, "construir_monitoreo", lambda _c: _Monitoreo(_informe("deuda 10 → 20, línea base"))
    )
    assert monitorear.main() == 0
    salida = capsys.readouterr().out
    assert salida.isascii() and "informeId" in salida


def test_G5_si_gestion_no_responde_el_job_sale_con_codigo_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(monitorear, "construir_monitoreo", lambda _c: _Monitoreo(None))
    assert monitorear.main() == 1
    assert "Gestión caída" in capsys.readouterr().err
