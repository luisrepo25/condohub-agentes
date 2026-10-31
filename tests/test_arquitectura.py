"""Arquitectura Clean (H): el dominio y la aplicación no dependen de frameworks ni de la infraestructura.

Las dependencias apuntan siempre hacia el dominio: `domain` solo usa la librería estándar; `application`
solo usa la estándar y `domain`; nada de aquí importa `infrastructure` ni `api`. Se comprueba leyendo los
`import` de cada archivo.
"""

import ast
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1] / "app"
ESTANDAR = set(sys.stdlib_module_names)
PROHIBIDAS = {
    "domain": ("app.application", "app.infrastructure", "app.api"),
    "application": ("app.infrastructure", "app.api"),
}


def _modulos_importados(archivo: Path) -> list[tuple[int, str]]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    encontrados: list[tuple[int, str]] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            encontrados += [(nodo.lineno, a.name) for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            encontrados.append((nodo.lineno, nodo.module))
    return encontrados


def violaciones(capa: str, raiz: Path = RAIZ) -> list[str]:
    """Imports de `capa` que son de terceros o que apuntan a una capa exterior."""
    problemas: list[str] = []
    for archivo in sorted((raiz / capa).rglob("*.py")):
        for linea, modulo in _modulos_importados(archivo):
            superior = modulo.split(".")[0]
            prohibido = modulo.startswith(PROHIBIDAS[capa])
            tercero = superior != "app" and superior not in ESTANDAR
            if prohibido or tercero:
                problemas.append(f"{archivo.relative_to(raiz.parent)}:{linea} importa «{modulo}»")
    return problemas


@pytest.mark.parametrize("capa", ["domain", "application"])
def test_H_Clean_la_capa_solo_depende_de_la_libreria_estandar_y_de_capas_interiores(capa: str) -> None:
    assert violaciones(capa) == []


def test_H_Clean_la_comprobacion_detecta_un_framework_y_una_capa_exterior(tmp_path: Path) -> None:
    (tmp_path / "app" / "domain").mkdir(parents=True)
    (tmp_path / "app" / "domain" / "malo.py").write_text(
        "import fastapi\nfrom app.infrastructure.mongo import repositorio\nfrom datetime import datetime\n",
        encoding="utf-8",
    )

    encontradas = violaciones("domain", tmp_path / "app")

    assert len(encontradas) == 2
    assert any("fastapi" in p for p in encontradas) and any(
        "app.infrastructure.mongo" in p for p in encontradas
    )


def test_H_Clean_application_puede_importar_domain_pero_domain_no_puede_importar_application(
    tmp_path: Path,
) -> None:
    (tmp_path / "app" / "application").mkdir(parents=True)
    (tmp_path / "app" / "domain").mkdir(parents=True)
    (tmp_path / "app" / "application" / "caso.py").write_text(
        "from app.domain.reportes import Reporte\n", encoding="utf-8"
    )
    (tmp_path / "app" / "domain" / "malo.py").write_text(
        "from app.application.reportes import CasosReportes\n", encoding="utf-8"
    )

    assert violaciones("application", tmp_path / "app") == []
    assert len(violaciones("domain", tmp_path / "app")) == 1
