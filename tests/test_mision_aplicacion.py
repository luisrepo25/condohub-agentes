"""Misiones de punta a punta con un LLM guionado: lecturas libres, escrituras solo con la aprobación del
ADMIN (G2)."""

from uuid import UUID

import pytest

from app.application.mision import (
    ArgumentosInvalidos,
    ConfirmacionNoEncontrada,
    ConfirmarAccion,
    ConflictoDeVersion,
    ConsultarMision,
    EjecutarMision,
    IniciarMision,
    LLMNoDisponible,
    MisionNoEncontrada,
    RechazarAccion,
    SolicitarAccion,
    reconstruir_conversacion,
)
from app.domain.mision import (
    ConfirmacionYaResuelta,
    EstadoConfirmacion,
    EstadoMision,
    TipoMision,
    TipoPaso,
)
from tests.dobles_mision import LLMGuionado, Mundo, RecargosFalsos, llama, texto

ADMIN = "admin-1"
OTRO_ADMIN = "admin-2"


def _caso(
    mundo: Mundo,
) -> tuple[IniciarMision, EjecutarMision, ConfirmarAccion, RechazarAccion, ConsultarMision]:
    base = (mundo.misiones, mundo.confirmaciones, mundo.bitacora, mundo.reloj)
    return (
        IniciarMision(*base),
        EjecutarMision(*base, mundo.catalogo, mundo.llm),
        ConfirmarAccion(*base, mundo.catalogo),
        RechazarAccion(*base, mundo.catalogo),
        ConsultarMision(*base),
    )


def _lanzar(mundo: Mundo, limite: int = 15) -> UUID:
    iniciar, ejecutar, *_ = _caso(mundo)
    mision = iniciar.iniciar(
        ADMIN, TipoMision.GESTIONAR_MOROSIDAD, "Gestiona la morosidad de octubre", limite
    )
    ejecutar.ejecutar(mision.id)
    return mision.id


RECORDATORIO = {"unidadId": "u1", "mensaje": "Estimado propietario, tiene 2 expensas vencidas."}


def test_G1_la_mision_solo_con_lecturas_se_completa_sin_pedir_nada_al_admin() -> None:
    mundo = Mundo(LLMGuionado(llama("consultar_morosos"), texto("Hay 2 morosos con 510.50 vencidos.")))
    mision_id = _lanzar(mundo)
    vista = _caso(mundo)[4].ver(mision_id)
    assert vista.mision.estado is EstadoMision.COMPLETADA and "510.50" in (vista.mision.resumen or "")
    assert vista.confirmaciones == [] and vista.mision.pasos_ejecutados == 2


def test_G3_la_bitacora_guarda_cada_paso_en_orden() -> None:
    mundo = Mundo(LLMGuionado(llama("consultar_morosos"), texto("Listo.")))
    pasos = _caso(mundo)[4].ver(_lanzar(mundo)).pasos
    assert [p.tipo for p in pasos] == [
        TipoPaso.LLAMADA_HERRAMIENTA,
        TipoPaso.RESULTADO_HERRAMIENTA,
        TipoPaso.RAZONAMIENTO,
        TipoPaso.FIN,
    ]
    assert [p.paso for p in pasos] == [1, 2, 3, 4]
    assert pasos[0].herramienta == "consultar_morosos" and pasos[1].salida and pasos[1].salida["total"] == 2


def test_G2_pedir_un_recordatorio_no_lo_envia_queda_pendiente_del_admin() -> None:
    mundo = Mundo(LLMGuionado(llama("consultar_morosos"), llama("enviar_recordatorio", "c2", **RECORDATORIO)))
    vista = _caso(mundo)[4].ver(_lanzar(mundo))
    assert vista.mision.estado is EstadoMision.ESPERANDO_CONFIRMACION
    assert mundo.recordatorios.enviados == []  # nada salió
    assert len(vista.confirmaciones) == 1 and vista.confirmaciones[0].estado is EstadoConfirmacion.PENDIENTE
    assert vista.pasos[-1].tipo is TipoPaso.CONFIRMACION


def test_G2_al_aprobar_se_ejecuta_una_vez_y_queda_quien_aprobo() -> None:
    mundo = Mundo(
        LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO), texto("Recordatorio enviado a u1."))
    )
    _, ejecutar, confirmar, _, consultar = _caso(mundo)
    mision_id = _lanzar(mundo)
    confirmacion_id = consultar.ver(mision_id).confirmaciones[0].id
    resolucion = confirmar.aprobar(confirmacion_id, ADMIN)
    assert resolucion.continuar_mision and resolucion.confirmacion.estado is EstadoConfirmacion.EJECUTADA
    assert mundo.recordatorios.enviados == [("u1", RECORDATORIO["mensaje"])]
    ejecutar.ejecutar(mision_id)  # el agente sigue y cierra
    vista = consultar.ver(mision_id)
    assert vista.mision.estado is EstadoMision.COMPLETADA
    resultado = next(p for p in vista.pasos if p.tipo is TipoPaso.RESULTADO_HERRAMIENTA)
    assert resultado.confirmado_por == ADMIN and resultado.confirmacion_id == confirmacion_id  # G3
    assert vista.confirmaciones[0].resuelta_por == ADMIN and vista.confirmaciones[0].resuelta_en is not None


def test_G2_el_llm_ve_el_resultado_aprobado_al_continuar() -> None:
    llm = LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO), texto("Hecho."))
    mundo = Mundo(llm)
    _, ejecutar, confirmar, _, consultar = _caso(mundo)
    mision_id = _lanzar(mundo)
    confirmar.aprobar(consultar.ver(mision_id).confirmaciones[0].id, ADMIN)
    ejecutar.ejecutar(mision_id)
    ultimo = llm.llamadas[-1][-1]
    assert ultimo.rol == "tool" and '"enviado": true' in (ultimo.contenido or "")


def test_G2_si_el_admin_rechaza_no_se_ejecuta_y_el_agente_lo_sabe() -> None:
    llm = LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO), texto("El ADMIN no autorizó el envío."))
    mundo = Mundo(llm)
    _, ejecutar, _, rechazar, consultar = _caso(mundo)
    mision_id = _lanzar(mundo)
    resolucion = rechazar.rechazar(consultar.ver(mision_id).confirmaciones[0].id, OTRO_ADMIN)
    assert resolucion.confirmacion.estado is EstadoConfirmacion.RECHAZADA and resolucion.continuar_mision
    assert mundo.recordatorios.enviados == []
    ejecutar.ejecutar(mision_id)
    assert "rechaz" in (llm.llamadas[-1][-1].contenido or "").lower()
    assert consultar.ver(mision_id).mision.estado is EstadoMision.COMPLETADA


def test_G2_aprobar_dos_veces_es_conflicto_y_no_se_ejecuta_otra_vez() -> None:
    mundo = Mundo(LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO)))
    _, _, confirmar, rechazar, consultar = _caso(mundo)
    confirmacion_id = consultar.ver(_lanzar(mundo)).confirmaciones[0].id
    confirmar.aprobar(confirmacion_id, ADMIN)
    with pytest.raises(ConfirmacionYaResuelta):
        confirmar.aprobar(confirmacion_id, OTRO_ADMIN)
    with pytest.raises(ConfirmacionYaResuelta):
        rechazar.rechazar(confirmacion_id, OTRO_ADMIN)
    assert len(mundo.recordatorios.enviados) == 1


def test_G2_dos_admins_a_la_vez_solo_ejecutan_una_vez_bloqueo_optimista() -> None:
    mundo = Mundo(LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO)))
    _, _, confirmar, _, consultar = _caso(mundo)
    confirmacion_id = consultar.ver(_lanzar(mundo)).confirmaciones[0].id

    original = mundo.confirmaciones.obtener
    llamadas = {"n": 0}

    def obtener_y_dejar_que_otro_se_adelante(i: UUID):  # type: ignore[no-untyped-def]
        copia = original(i)
        llamadas["n"] += 1
        if llamadas["n"] == 1:  # el otro ADMIN aprueba justo después de que leímos
            otro = original(i)
            assert otro is not None
            otro.aprobar(OTRO_ADMIN, mundo.reloj.ahora())
            mundo.confirmaciones.guardar(otro)
        return copia

    mundo.confirmaciones.obtener = obtener_y_dejar_que_otro_se_adelante  # type: ignore[method-assign]
    with pytest.raises(ConflictoDeVersion):
        confirmar.aprobar(confirmacion_id, ADMIN)
    assert mundo.recordatorios.enviados == []  # el perdedor de la carrera no ejecutó nada


def test_F5_si_la_accion_falla_tras_aprobar_queda_fallida_y_el_agente_se_entera() -> None:
    llm = LLMGuionado(
        llama("proponer_recargo", unidadId="u1", monto="7.80", motivo="Mora de 1 mes"), texto("No se pudo.")
    )
    mundo = Mundo(llm, RecargosFalsos(falla=True))
    _, ejecutar, confirmar, _, consultar = _caso(mundo)
    mision_id = _lanzar(mundo)
    resolucion = confirmar.aprobar(consultar.ver(mision_id).confirmaciones[0].id, ADMIN)
    assert resolucion.confirmacion.estado is EstadoConfirmacion.FALLIDA
    assert "proponerRecargo" in (resolucion.confirmacion.resultado or {})["error"]
    ejecutar.ejecutar(mision_id)
    assert "error" in (llm.llamadas[-1][-1].contenido or "")


def test_F5_el_recargo_propuesto_solo_se_registra_tras_la_aprobacion() -> None:
    mundo = Mundo(
        LLMGuionado(
            llama("calcular_recargo", deudaVencida="390.00"),
            llama("proponer_recargo", "c2", unidadId="u1", monto="7.80", motivo="Mora de 1 mes"),
        )
    )
    _, _, confirmar, _, consultar = _caso(mundo)
    vista = consultar.ver(_lanzar(mundo))
    assert vista.confirmaciones[0].riesgo.value == "DINERO" and mundo.recargos.propuestos == []
    confirmar.aprobar(vista.confirmaciones[0].id, ADMIN)
    assert [(u, str(m)) for u, m, _ in mundo.recargos.propuestos] == [("u1", "7.80")]


def test_G2_argumentos_invalidos_vuelven_al_llm_y_no_crean_confirmacion() -> None:
    llm = LLMGuionado(llama("proponer_recargo", unidadId="u1", monto="-5", motivo="x"), texto("Corregiré."))
    mundo = Mundo(llm)
    vista = _caso(mundo)[4].ver(_lanzar(mundo))
    assert vista.confirmaciones == [] and vista.mision.estado is EstadoMision.COMPLETADA
    assert "error" in (llm.llamadas[-1][-1].contenido or "")


def test_G2_una_herramienta_que_no_existe_no_ejecuta_nada() -> None:
    llm = LLMGuionado(llama("borrar_todo"), texto("No puedo."))
    mundo = Mundo(llm)
    vista = _caso(mundo)[4].ver(_lanzar(mundo))
    assert vista.confirmaciones == [] and "desconocida" in (llm.llamadas[-1][-1].contenido or "")


def test_G1_al_llegar_al_limite_de_pasos_la_mision_termina_incompleta() -> None:
    mundo = Mundo(LLMGuionado(*[llama("pagos_pendientes", f"c{i}") for i in range(10)]))
    vista = _caso(mundo)[4].ver(_lanzar(mundo, limite=3))
    assert vista.mision.estado is EstadoMision.INCOMPLETA and vista.mision.pasos_ejecutados == 3
    assert vista.pasos[-1].tipo is TipoPaso.FIN


def test_G1_si_el_llm_no_responde_la_mision_queda_en_error_con_su_rastro() -> None:
    mundo = Mundo(LLMGuionado(LLMNoDisponible("sin clave")))
    vista = _caso(mundo)[4].ver(_lanzar(mundo))
    assert vista.mision.estado is EstadoMision.ERROR and "sin clave" in (vista.mision.resumen or "")
    assert vista.pasos[-1].tipo is TipoPaso.ERROR


def test_G3_la_conversacion_se_reconstruye_desde_la_bitacora_tras_un_reinicio() -> None:
    mundo = Mundo(LLMGuionado(llama("consultar_morosos"), llama("enviar_recordatorio", "c2", **RECORDATORIO)))
    _, _, _, _, consultar = _caso(mundo)
    vista = consultar.ver(_lanzar(mundo))
    mensajes = reconstruir_conversacion(vista.mision, vista.pasos)
    assert [m.rol for m in mensajes] == ["user", "assistant", "tool", "assistant"]
    assert mensajes[1].llamada and mensajes[1].llamada.nombre == "consultar_morosos"
    assert mensajes[2].llamada_id == "c1" and mensajes[3].llamada and mensajes[3].llamada.id == "c2"


def test_G1_una_mision_en_espera_no_avanza_sola() -> None:
    llm = LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO))
    mundo = Mundo(llm)
    mision_id = _lanzar(mundo)
    _caso(mundo)[1].ejecutar(mision_id)  # otra vez: sigue esperando
    assert (
        len(llm.llamadas) == 1
        and _caso(mundo)[4].ver(mision_id).mision.estado is EstadoMision.ESPERANDO_CONFIRMACION
    )


def test_G1_ver_una_mision_o_confirmacion_inexistente_es_no_encontrado() -> None:
    mundo = Mundo()
    _, _, confirmar, rechazar, consultar = _caso(mundo)
    desconocido = UUID(int=7)
    with pytest.raises(MisionNoEncontrada):
        consultar.ver(desconocido)
    with pytest.raises(ConfirmacionNoEncontrada):
        confirmar.aprobar(desconocido, ADMIN)
    with pytest.raises(ConfirmacionNoEncontrada):
        rechazar.rechazar(desconocido, ADMIN)


# --- Solicitudes que llegan por MCP desde un cliente externo: mismo candado (G2) ---


def _solicitar(mundo: Mundo) -> SolicitarAccion:
    return SolicitarAccion(mundo.misiones, mundo.confirmaciones, mundo.bitacora, mundo.reloj, mundo.catalogo)


def test_G2_una_escritura_pedida_por_mcp_tambien_queda_pendiente() -> None:
    mundo = Mundo()
    confirmacion = _solicitar(mundo).solicitar("enviar_recordatorio", RECORDATORIO)
    assert confirmacion.estado is EstadoConfirmacion.PENDIENTE and mundo.recordatorios.enviados == []
    mision = mundo.misiones.obtener(confirmacion.mision_id)
    assert mision and mision.estado is EstadoMision.ESPERANDO_CONFIRMACION and not mision.con_llm


def test_G2_aprobada_la_solicitud_mcp_se_ejecuta_y_cierra_sin_llm() -> None:
    mundo = Mundo()
    confirmacion = _solicitar(mundo).solicitar("enviar_recordatorio", RECORDATORIO)
    resolucion = _caso(mundo)[2].aprobar(confirmacion.id, ADMIN)
    assert not resolucion.continuar_mision and mundo.recordatorios.enviados
    mision = mundo.misiones.obtener(confirmacion.mision_id)
    assert mision and mision.estado is EstadoMision.COMPLETADA


def test_G2_rechazada_la_solicitud_mcp_se_cancela() -> None:
    mundo = Mundo()
    confirmacion = _solicitar(mundo).solicitar("enviar_recordatorio", RECORDATORIO)
    _caso(mundo)[3].rechazar(confirmacion.id, ADMIN)
    mision = mundo.misiones.obtener(confirmacion.mision_id)
    assert mision and mision.estado is EstadoMision.CANCELADA and mundo.recordatorios.enviados == []


@pytest.mark.parametrize(
    ("herramienta", "argumentos"),
    [("consultar_morosos", {}), ("borrar_todo", {}), ("enviar_recordatorio", {"unidadId": "u1"})],
)
def test_G2_por_mcp_solo_se_piden_escrituras_validas(herramienta: str, argumentos: dict[str, object]) -> None:
    with pytest.raises(ArgumentosInvalidos):
        _solicitar(Mundo()).solicitar(herramienta, argumentos)
