"""G1-G3 y F5 en el dominio: la misión, la confirmación del ADMIN (nada se ejecuta sin ella) y sus límites."""

from datetime import UTC, datetime

import pytest

from app.domain.mision import (
    ConfirmacionPendiente,
    ConfirmacionYaResuelta,
    EstadoConfirmacion,
    EstadoMision,
    Mision,
    Riesgo,
    TipoMision,
    TransicionInvalida,
)

AHORA = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def mision(limite: int = 3) -> Mision:
    return Mision.nueva(
        TipoMision.GESTIONAR_MOROSIDAD, "Gestiona la morosidad de octubre", "admin-1", AHORA, limite
    )


def confirmacion(riesgo: Riesgo = Riesgo.DINERO) -> ConfirmacionPendiente:
    return ConfirmacionPendiente.nueva(
        mision().id, "proponer_recargo", {"unidadId": "u1", "monto": "7.80"}, riesgo, "Mora de 1 mes", AHORA
    )


def test_G1_una_mision_nueva_esta_en_curso_y_sin_pasos() -> None:
    m = mision()
    assert m.estado is EstadoMision.EN_CURSO and m.pasos_ejecutados == 0 and m.limite_pasos == 3


@pytest.mark.parametrize("objetivo", ["", "   "])
def test_G1_la_mision_necesita_un_objetivo(objetivo: str) -> None:
    with pytest.raises(ValueError):
        Mision.nueva(TipoMision.LIBRE, objetivo, "admin-1", AHORA)


def test_G3_la_mision_la_inicia_un_admin_identificado() -> None:
    with pytest.raises(ValueError):
        Mision.nueva(TipoMision.LIBRE, "algo", "", AHORA)


@pytest.mark.parametrize("limite", [0, 51])
def test_G1_el_limite_de_pasos_esta_entre_1_y_50(limite: int) -> None:
    with pytest.raises(ValueError):
        mision(limite)


def test_G1_al_llegar_al_limite_de_pasos_no_se_puede_seguir() -> None:
    m = mision(limite=2)
    m.registrar_paso()
    m.registrar_paso()
    assert m.alcanzo_el_limite
    with pytest.raises(TransicionInvalida):
        m.registrar_paso()


def test_G2_la_mision_espera_la_confirmacion_y_se_reanuda() -> None:
    m = mision()
    m.esperar_confirmacion()
    assert m.estado is EstadoMision.ESPERANDO_CONFIRMACION
    with pytest.raises(TransicionInvalida):
        m.registrar_paso()  # esperando al ADMIN no avanza sola
    m.reanudar()
    assert m.estado is EstadoMision.EN_CURSO


def test_G1_completar_guarda_el_resumen_y_la_fecha() -> None:
    m = mision()
    m.completar("3 morosos; recordatorios enviados", AHORA)
    assert m.estado is EstadoMision.COMPLETADA and m.resumen and m.terminada_en == AHORA
    with pytest.raises(TransicionInvalida):
        m.completar("otra vez", AHORA)


def test_G1_una_mision_terminada_no_admite_mas_cambios() -> None:
    m = mision()
    m.marcar_incompleta("límite de pasos", AHORA)
    for operacion in (m.esperar_confirmacion, m.reanudar):
        with pytest.raises(TransicionInvalida):
            operacion()


def test_G2_una_herramienta_de_lectura_no_necesita_confirmacion() -> None:
    with pytest.raises(ValueError):
        confirmacion(Riesgo.LECTURA)


@pytest.mark.parametrize("riesgo", [Riesgo.ESCRITURA, Riesgo.DINERO])
def test_G2_las_escrituras_nacen_pendientes(riesgo: Riesgo) -> None:
    c = confirmacion(riesgo)
    assert c.estado is EstadoConfirmacion.PENDIENTE and not c.puede_ejecutarse and c.resuelta_por is None


def test_G2_no_se_ejecuta_lo_que_no_aprobo_un_admin() -> None:
    c = confirmacion()
    with pytest.raises(TransicionInvalida):
        c.registrar_ejecucion({"ok": True})
    with pytest.raises(TransicionInvalida):
        c.registrar_fallo("x")


def test_G3_aprobar_registra_quien_y_cuando() -> None:
    c = confirmacion()
    c.aprobar("admin-1", AHORA)
    assert c.estado is EstadoConfirmacion.APROBADA and c.resuelta_por == "admin-1" and c.resuelta_en == AHORA
    assert c.puede_ejecutarse and c.version == 1


def test_G2_aprobada_y_ejecutada_guarda_el_resultado() -> None:
    c = confirmacion()
    c.aprobar("admin-1", AHORA)
    c.registrar_ejecucion({"propuestaId": "p1"})
    assert (
        c.estado is EstadoConfirmacion.EJECUTADA and c.resultado == {"propuestaId": "p1"} and c.version == 2
    )


def test_G2_si_la_ejecucion_falla_queda_fallida_con_el_motivo() -> None:
    c = confirmacion()
    c.aprobar("admin-1", AHORA)
    c.registrar_fallo("Gestión no responde")
    assert c.estado is EstadoConfirmacion.FALLIDA and c.resultado == {"error": "Gestión no responde"}


def test_G2_rechazar_deja_constancia_y_no_se_puede_ejecutar() -> None:
    c = confirmacion()
    c.rechazar("admin-2", AHORA)
    assert c.estado is EstadoConfirmacion.RECHAZADA and c.resuelta_por == "admin-2" and not c.puede_ejecutarse
    with pytest.raises(TransicionInvalida):
        c.registrar_ejecucion({})


@pytest.mark.parametrize("segunda", ["aprobar", "rechazar"])
def test_G2_una_confirmacion_no_se_resuelve_dos_veces(segunda: str) -> None:
    c = confirmacion()
    c.aprobar("admin-1", AHORA)
    with pytest.raises(ConfirmacionYaResuelta):
        getattr(c, segunda)("admin-2", AHORA)


def test_G3_resolver_exige_un_admin_identificado() -> None:
    with pytest.raises(ValueError):
        confirmacion().aprobar("", AHORA)
