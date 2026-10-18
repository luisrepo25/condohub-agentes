"""Misiones, confirmaciones y bitácora contra un MongoDB REAL con los validadores de `db/mongo-init.js`.

Se omiten si no hay Mongo. Preparar: `docker compose -f infra/docker-compose.yml up -d mongo` y
`AGENTES_DB=agentes_pruebas mongosh mongodb://localhost:27017 db/mongo-init.js`.
"""

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.application.mision import (
    ConfirmarAccion,
    ConflictoDeVersion,
    ConsultarMision,
    EjecutarMision,
    IniciarMision,
)
from app.domain.mision import (
    ConfirmacionPendiente,
    ConfirmacionYaResuelta,
    EstadoConfirmacion,
    EstadoMision,
    Mision,
    PasoBitacora,
    Riesgo,
    TipoMision,
    TipoPaso,
)
from tests.dobles_mision import AHORA, LLMGuionado, Mundo, llama, texto

pymongo = pytest.importorskip("pymongo")

URI = os.environ.get("MONGO_URI_PRUEBAS", "mongodb://localhost:27017")
BASE = os.environ.get("MONGO_DB_PRUEBAS", "agentes_pruebas")
COLECCIONES = ("misiones", "confirmaciones", "bitacora")


@pytest.fixture()
def base() -> Iterator[Any]:
    cliente: Any = pymongo.MongoClient(URI, tz_aware=True, serverSelectionTimeoutMS=1500)
    try:
        cliente.admin.command("ping")
    except Exception:
        pytest.skip("No hay un MongoDB disponible (docker compose up -d mongo)")
    db = cliente[BASE]
    for nombre in COLECCIONES:
        opciones = db.command("listCollections", filter={"name": nombre})["cursor"]["firstBatch"]
        if not opciones or "validator" not in opciones[0].get("options", {}):
            pytest.skip(
                f"Sin el validador de «{nombre}»: ejecuta db/mongo-init.js con AGENTES_DB=agentes_pruebas"
            )
        db[nombre].delete_many({})
    yield db
    cliente.close()


def _repos(base: Any) -> Any:
    from app.infrastructure.mongo.misiones import BitacoraMongo, ConfirmacionesMongo, MisionesMongo

    return MisionesMongo(base), ConfirmacionesMongo(base), BitacoraMongo(base)


def _mision() -> Mision:
    return Mision.nueva(TipoMision.GESTIONAR_MOROSIDAD, "Gestiona la morosidad", "admin-1", AHORA, 7)


def test_G1_la_mision_se_guarda_y_se_lee_igual(base: Any) -> None:
    misiones, _, _ = _repos(base)
    m = _mision()
    m.registrar_paso()
    m.esperar_confirmacion()
    misiones.guardar(m)
    leida = misiones.obtener(m.id)
    assert leida == m and leida.limite_pasos == 7 and leida.creada_en.tzinfo is not None
    m.reanudar()
    m.completar("listo", AHORA)
    misiones.guardar(m)  # actualiza, no duplica
    assert (
        misiones.obtener(m.id).estado is EstadoMision.COMPLETADA and base["misiones"].count_documents({}) == 1
    )
    assert misiones.obtener(uuid4()) is None


def test_G2_la_confirmacion_se_guarda_y_se_resuelve_con_version(base: Any) -> None:
    _, confirmaciones, _ = _repos(base)
    c = ConfirmacionPendiente.nueva(
        uuid4(),
        "enviar_recordatorio",
        {"unidadId": "u1", "mensaje": "Hola"},
        Riesgo.ESCRITURA,
        "x",
        AHORA,
        "c1",
    )
    confirmaciones.guardar(c)
    c.aprobar("admin-1", AHORA)
    confirmaciones.guardar(c)
    c.registrar_ejecucion({"enviado": True})
    confirmaciones.guardar(c)
    leida = confirmaciones.obtener(c.id)
    assert leida == c and leida.estado is EstadoConfirmacion.EJECUTADA and leida.version == 2
    assert [x.id for x in confirmaciones.de_mision(c.mision_id)] == [c.id]


def test_G2_dos_admins_con_la_misma_lectura_solo_uno_resuelve(base: Any) -> None:
    _, confirmaciones, _ = _repos(base)
    c = ConfirmacionPendiente.nueva(
        uuid4(), "enviar_recordatorio", {"unidadId": "u1", "mensaje": "Hola"}, Riesgo.ESCRITURA, "x", AHORA
    )
    confirmaciones.guardar(c)
    a, b = confirmaciones.obtener(c.id), confirmaciones.obtener(c.id)
    assert a and b
    a.aprobar("admin-1", AHORA)
    b.rechazar("admin-2", AHORA)
    confirmaciones.guardar(a)
    with pytest.raises(ConflictoDeVersion):
        confirmaciones.guardar(b)  # el segundo llega tarde: no pisa al primero
    assert confirmaciones.obtener(c.id).resuelta_por == "admin-1"  # type: ignore[union-attr]


def test_G2_no_se_puede_insertar_dos_veces_la_misma_confirmacion(base: Any) -> None:
    _, confirmaciones, _ = _repos(base)
    c = ConfirmacionPendiente.nueva(
        uuid4(), "enviar_recordatorio", {"unidadId": "u1", "mensaje": "Hola"}, Riesgo.ESCRITURA, "x", AHORA
    )
    confirmaciones.guardar(c)
    with pytest.raises(ConflictoDeVersion):
        confirmaciones.guardar(c)


def test_G3_la_bitacora_vuelve_en_orden_con_quien_confirmo(base: Any) -> None:
    _, _, bitacora = _repos(base)
    mision_id, conf_id = uuid4(), uuid4()
    pasos = [
        PasoBitacora(
            mision_id,
            2,
            TipoPaso.RESULTADO_HERRAMIENTA,
            AHORA,
            "enviar_recordatorio",
            None,
            {"enviado": True},
            "c1",
            conf_id,
            "admin-1",
        ),
        PasoBitacora(
            mision_id,
            1,
            TipoPaso.LLAMADA_HERRAMIENTA,
            AHORA,
            "enviar_recordatorio",
            {"unidadId": "u1"},
            None,
            "c1",
        ),
    ]
    for p in pasos:
        bitacora.agregar(p)
    leidos = bitacora.listar(mision_id)
    assert [p.paso for p in leidos] == [1, 2]
    assert (
        leidos[1].confirmado_por == "admin-1"
        and leidos[1].confirmacion_id == conf_id
        and leidos[0].entrada == {"unidadId": "u1"}
    )
    assert bitacora.listar(uuid4()) == []


def test_G2_el_validador_no_deja_resolver_sin_decir_quien(base: Any) -> None:
    _, confirmaciones, _ = _repos(base)
    c = ConfirmacionPendiente.nueva(
        uuid4(), "enviar_recordatorio", {"unidadId": "u1", "mensaje": "Hola"}, Riesgo.ESCRITURA, "x", AHORA
    )
    confirmaciones.guardar(c)
    doc = base["confirmaciones"].find_one({"id": str(c.id)})
    doc.pop("_id")
    doc.update(id=str(uuid4()), estado="APROBADA", resueltaPor=None, resueltaEn=None)
    with pytest.raises(pymongo.errors.WriteError):
        base["confirmaciones"].insert_one(doc)


def test_G2_el_validador_rechaza_estados_invalidos(base: Any) -> None:
    with pytest.raises(pymongo.errors.WriteError):
        base["misiones"].insert_one(
            {
                "id": "x",
                "tipo": "LIBRE",
                "objetivo": "o",
                "estado": "HACKEADA",
                "iniciadaPor": "a",
                "pasosEjecutados": 0,
                "limitePasos": 5,
                "creadaEn": AHORA,
            }
        )


def test_G1_una_mision_completa_con_aprobacion_sobre_mongo_real(base: Any) -> None:
    """Todo el recorrido con las tres colecciones reales: pedir, esperar, aprobar una sola vez y terminar."""
    misiones, confirmaciones, bitacora = _repos(base)
    mundo = Mundo(
        LLMGuionado(
            llama("consultar_morosos"),
            llama("enviar_recordatorio", "c2", unidadId="u1", mensaje="Tiene 2 expensas vencidas."),
            texto("Se envió el recordatorio a u1."),
        )
    )
    rep = (misiones, confirmaciones, bitacora, mundo.reloj)
    mision = IniciarMision(*rep).iniciar(
        "admin-1", TipoMision.GESTIONAR_MOROSIDAD, "Gestiona la morosidad", 15
    )
    ejecutar = EjecutarMision(*rep, mundo.catalogo, mundo.llm)
    assert ejecutar.ejecutar(mision.id).estado is EstadoMision.ESPERANDO_CONFIRMACION
    pendiente = ConsultarMision(*rep).ver(mision.id).confirmaciones[0]
    confirmar = ConfirmarAccion(*rep, mundo.catalogo)
    assert confirmar.aprobar(pendiente.id, "admin-1").continuar_mision
    with pytest.raises(ConfirmacionYaResuelta):
        confirmar.aprobar(pendiente.id, "admin-2")
    ejecutar.ejecutar(mision.id)
    vista = ConsultarMision(*rep).ver(mision.id)
    assert vista.mision.estado is EstadoMision.COMPLETADA and mundo.recordatorios.enviados == [
        ("u1", "Tiene 2 expensas vencidas.")
    ]
    assert [p.tipo for p in vista.pasos].count(TipoPaso.RESULTADO_HERRAMIENTA) == 2
    assert any(p.confirmado_por == "admin-1" for p in vista.pasos) and isinstance(
        vista.pasos[0].mision_id, UUID
    )
