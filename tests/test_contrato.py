"""Rutas y métodos implementados = los de contracts/openapi/agentes.yaml (si el contrato está a mano)."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

CONTRATO = Path(__file__).resolve().parents[3] / "contracts" / "openapi" / "agentes.yaml"
METODOS = {"get", "post", "put", "patch", "delete"}


def _operaciones(paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
    return {(metodo.upper(), ruta) for ruta, ops in paths.items() for metodo in ops if metodo in METODOS}


@pytest.mark.skipif(not CONTRATO.exists(), reason="agentes.yaml aún no existe o el repo está abierto solo")
def test_las_operaciones_coinciden_con_el_contrato(client: TestClient) -> None:
    contrato = yaml.safe_load(CONTRATO.read_text(encoding="utf-8"))
    implementadas = _operaciones(client.app.openapi()["paths"])  # type: ignore[attr-defined]
    assert implementadas == _operaciones(contrato["paths"])
