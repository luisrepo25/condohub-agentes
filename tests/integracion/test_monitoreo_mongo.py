"""Repositorios del monitoreo contra un MongoDB REAL con el validador de `db/mongo-init.js`.

Se omiten si no hay Mongo. Preparar: `docker compose -f infra/docker-compose.yml up -d mongo` y
`AGENTES_DB=agentes_pruebas mongosh mongodb://localhost:27017 db/mongo-init.js`.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.domain.monitoreo import Alerta, Informe, Metricas, Origen, Severidad, TipoAnomalia

pymongo = pytest.importorskip("pymongo")

URI = os.environ.get("MONGO_URI_PRUEBAS", "mongodb://localhost:27017")
BASE = os.environ.get("MONGO_DB_PRUEBAS", "agentes_pruebas")
T0 = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


@pytest.fixture()
def base() -> Iterator[Any]:
    cliente: Any = pymongo.MongoClient(URI, tz_aware=True, serverSelectionTimeoutMS=1500)
    try:
        cliente.admin.command("ping")
    except Exception:
        pytest.skip("No hay un MongoDB disponible (docker compose up -d mongo)")
    db = cliente[BASE]
    for nombre in ("metricas", "informes"):
        if nombre not in db.list_collection_names() or "validator" not in db.command(
            "listCollections", filter={"name": nombre}
        )["cursor"]["firstBatch"][0].get("options", {}):
            pytest.skip(
                f"Sin el validador de «{nombre}»: ejecuta db/mongo-init.js con AGENTES_DB=agentes_pruebas"
            )
        db[nombre].delete_many({})
    yield db
    cliente.close()


def _metricas(dia: int, morosas: int = 5) -> Metricas:
    return Metricas(T0 + timedelta(days=dia), morosas, Decimal("1234.50"), 2, 3)


def test_G5_las_lecturas_vuelven_en_orden_y_con_el_dinero_exacto(base: Any) -> None:
    from app.infrastructure.mongo.monitoreo import MetricasMongo

    repo = MetricasMongo(base)
    for dia in range(5):
        repo.guardar(_metricas(dia, morosas=dia))
    ultimas = repo.ultimas(3)
    assert [m.unidades_morosas for m in ultimas] == [2, 3, 4]  # de la más antigua a la más reciente
    assert ultimas[0].deuda_vencida == Decimal("1234.50") and ultimas[0].generadas_en.tzinfo is not None
    assert repo.ultimas(0) == []


def test_G5_un_informe_se_guarda_y_se_lee_completo(base: Any) -> None:
    from app.infrastructure.mongo.monitoreo import InformesMongo

    repo = InformesMongo(base)
    alerta = Alerta(TipoAnomalia.PAGOS_SIN_CONCILIAR, Severidad.ALTA, "Hay 10 pagos", "10", "5")
    antiguo = Informe.nuevo(T0, Origen.PROGRAMADO, _metricas(0), (), "sin alertas", True)
    reciente = Informe.nuevo(
        T0 + timedelta(days=1), Origen.MANUAL, _metricas(1), (alerta,), "una alerta", False
    )
    repo.guardar(antiguo)
    repo.guardar(reciente.marcar_notificado())
    leidos = repo.ultimos(5)
    assert [i.id for i in leidos] == [reciente.id, antiguo.id]  # del más reciente al más antiguo
    assert leidos[0].alertas == (alerta,) and leidos[0].notificado and not leidos[1].notificado
    assert leidos[1].linea_base and leidos[0].metricas.deuda_vencida == Decimal("1234.50")


def test_F10_el_validador_rechaza_dinero_como_double(base: Any) -> None:
    with pytest.raises(pymongo.errors.WriteError):
        base["metricas"].insert_one(
            {"generadaEn": T0, "unidadesMorosas": 1, "deudaVencida": 10.5, "pagosPendientes": 0}
        )


def test_G5_el_validador_rechaza_un_informe_con_origen_desconocido(base: Any) -> None:
    from app.infrastructure.mongo.monitoreo import InformesMongo

    InformesMongo(base).guardar(Informe.nuevo(T0, Origen.MANUAL, _metricas(0), (), "ok", False))
    doc = base["informes"].find_one()
    doc.pop("_id")
    doc.update(informeId="otro-id", origen="HACKEADO")
    with pytest.raises(pymongo.errors.WriteError):
        base["informes"].insert_one(doc)
