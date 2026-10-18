"""API de misiones y confirmaciones: el ADMIN lanza, el agente pide, el ADMIN aprueba o rechaza y el agente
continúa."""

import pytest
from fastapi.testclient import TestClient

from app.application.mision import (
    ConfirmarAccion,
    ConsultarMision,
    EjecutarMision,
    IniciarMision,
    RechazarAccion,
    SolicitarAccion,
)
from app.infrastructure.composicion_agente import Agente
from app.infrastructure.keycloak import JwtVerificador
from app.main import create_app
from tests.conftest import ISSUER, CrearToken, _clave
from tests.dobles_mision import LLMGuionado, Mundo, llama, texto

ADMIN_A = "00000000-0000-0000-0000-00000000a001"
ADMIN_B = "00000000-0000-0000-0000-00000000a009"
RECORDATORIO = {"unidadId": "u1", "mensaje": "Estimado propietario, tiene 2 expensas vencidas."}


def _app(mundo: Mundo, llm_configurado: bool = True) -> TestClient:
    base = (mundo.misiones, mundo.confirmaciones, mundo.bitacora, mundo.reloj)
    agente = Agente(
        IniciarMision(*base),
        EjecutarMision(*base, mundo.catalogo, mundo.llm),
        ConfirmarAccion(*base, mundo.catalogo),
        RechazarAccion(*base, mundo.catalogo),
        ConsultarMision(*base),
        SolicitarAccion(*base, mundo.catalogo),
        mundo.catalogo,
        15,
        llm_configurado,
    )
    return TestClient(create_app(JwtVerificador(ISSUER, lambda _t: _clave.public_key()), agente=agente))


def _h(crear_token: CrearToken, sub: str = ADMIN_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {crear_token('ADMIN', sub=sub)}"}


def _lanzar(cliente: TestClient, h: dict[str, str]) -> str:
    r = cliente.post("/misiones", headers=h, json={"objetivo": "Gestiona la morosidad de octubre"})
    assert r.status_code == 202
    return str(r.json()["id"])


def test_G1_lanzar_responde_202_en_curso_y_el_agente_trabaja_en_segundo_plano(
    crear_token: CrearToken,
) -> None:
    mundo = Mundo(LLMGuionado(llama("consultar_morosos"), texto("Hay 2 morosos.")))
    cliente = _app(mundo)
    r = cliente.post(
        "/misiones", headers=_h(crear_token), json={"objetivo": "Gestiona la morosidad de octubre"}
    )
    assert (
        r.status_code == 202
        and r.json()["estado"] == "EN_CURSO"
        and r.json()["tipo"] == "GESTIONAR_MOROSIDAD"
    )
    final = cliente.get(f"/misiones/{r.json()['id']}", headers=_h(crear_token)).json()
    assert final["estado"] == "COMPLETADA" and final["resumen"] == "Hay 2 morosos."
    assert [p["tipo"] for p in final["pasos"]][:2] == ["LLAMADA_HERRAMIENTA", "RESULTADO_HERRAMIENTA"]  # G3


def test_G2_la_escritura_queda_pendiente_se_aprueba_y_el_agente_termina(crear_token: CrearToken) -> None:
    mundo = Mundo(LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO), texto("Recordatorio enviado.")))
    cliente = _app(mundo)
    mision_id = _lanzar(cliente, _h(crear_token))
    espera = cliente.get(f"/misiones/{mision_id}", headers=_h(crear_token)).json()
    assert espera["estado"] == "ESPERANDO_CONFIRMACION" and mundo.recordatorios.enviados == []
    pendiente = espera["confirmacionesPendientes"][0]
    assert pendiente["herramienta"] == "enviar_recordatorio" and pendiente["riesgo"] == "ESCRITURA"
    assert pendiente["estado"] == "PENDIENTE" and pendiente["argumentos"]["unidadId"] == "u1"

    r = cliente.post(f"/confirmaciones/{pendiente['id']}/aprobar", headers=_h(crear_token, ADMIN_B))
    assert r.status_code == 200 and r.json()["estado"] == "EJECUTADA"
    assert r.json()["resueltaPor"] == ADMIN_B and r.json()["resueltaEn"]  # G3: quién y cuándo
    assert len(mundo.recordatorios.enviados) == 1
    final = cliente.get(f"/misiones/{mision_id}", headers=_h(crear_token)).json()
    assert final["estado"] == "COMPLETADA" and final["confirmacionesPendientes"] == []
    assert any(p["confirmadoPor"] == ADMIN_B for p in final["pasos"])


def test_G2_rechazar_no_ejecuta_y_el_agente_continua(crear_token: CrearToken) -> None:
    mundo = Mundo(
        LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO), texto("El ADMIN no lo autorizó."))
    )
    cliente = _app(mundo)
    mision_id = _lanzar(cliente, _h(crear_token))
    confirmacion = cliente.get(f"/misiones/{mision_id}", headers=_h(crear_token)).json()[
        "confirmacionesPendientes"
    ][0]
    r = cliente.post(f"/confirmaciones/{confirmacion['id']}/rechazar", headers=_h(crear_token))
    assert r.status_code == 200 and r.json()["estado"] == "RECHAZADA" and mundo.recordatorios.enviados == []
    assert cliente.get(f"/misiones/{mision_id}", headers=_h(crear_token)).json()["estado"] == "COMPLETADA"


@pytest.mark.parametrize("segunda", ["aprobar", "rechazar"])
def test_G2_resolver_dos_veces_es_409_con_codigo_de_regla(crear_token: CrearToken, segunda: str) -> None:
    mundo = Mundo(LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO), texto("ok")))
    cliente = _app(mundo)
    mision_id = _lanzar(cliente, _h(crear_token))
    cid = cliente.get(f"/misiones/{mision_id}", headers=_h(crear_token)).json()["confirmacionesPendientes"][
        0
    ]["id"]
    assert cliente.post(f"/confirmaciones/{cid}/aprobar", headers=_h(crear_token)).status_code == 200
    r = cliente.post(f"/confirmaciones/{cid}/{segunda}", headers=_h(crear_token, ADMIN_B))
    assert r.status_code == 409 and r.json()["code"] == "G2"
    assert (
        r.headers["content-type"].startswith("application/problem+json")
        and len(mundo.recordatorios.enviados) == 1
    )


def test_G2_un_residente_no_puede_aprobar_una_accion_pendiente(crear_token: CrearToken) -> None:
    mundo = Mundo(LLMGuionado(llama("enviar_recordatorio", **RECORDATORIO)))
    cliente = _app(mundo)
    mision_id = _lanzar(cliente, _h(crear_token))
    cid = cliente.get(f"/misiones/{mision_id}", headers=_h(crear_token)).json()["confirmacionesPendientes"][
        0
    ]["id"]
    for rol in ("RESIDENTE", "GUARDIA"):
        r = cliente.post(
            f"/confirmaciones/{cid}/aprobar", headers={"Authorization": f"Bearer {crear_token(rol)}"}
        )
        assert r.status_code == 403
    assert mundo.recordatorios.enviados == []


def test_G1_si_la_accion_falla_tras_aprobar_la_confirmacion_queda_fallida(crear_token: CrearToken) -> None:
    from tests.dobles_mision import RecargosFalsos

    mundo = Mundo(
        LLMGuionado(
            llama("proponer_recargo", unidadId="u1", monto="7.80", motivo="Mora de 1 mes"),
            texto("No se pudo."),
        ),
        RecargosFalsos(falla=True),
    )
    cliente = _app(mundo)
    mision_id = _lanzar(cliente, _h(crear_token))
    espera = cliente.get(f"/misiones/{mision_id}", headers=_h(crear_token)).json()
    assert espera["confirmacionesPendientes"][0]["riesgo"] == "DINERO"
    r = cliente.post(
        f"/confirmaciones/{espera['confirmacionesPendientes'][0]['id']}/aprobar", headers=_h(crear_token)
    )
    assert r.status_code == 200 and r.json()["estado"] == "FALLIDA" and "error" in r.json()["resultado"]


@pytest.mark.parametrize(
    "cuerpo", [{"objetivo": ""}, {"objetivo": "x" * 501}, {"tipo": "GESTIONAR_MOROSIDAD"}]
)
def test_G1_una_solicitud_mal_formada_es_400(crear_token: CrearToken, cuerpo: dict[str, str]) -> None:
    assert _app(Mundo()).post("/misiones", headers=_h(crear_token), json=cuerpo).status_code == 400


def test_G1_un_tipo_de_mision_desconocido_es_400(crear_token: CrearToken) -> None:
    r = _app(Mundo()).post("/misiones", headers=_h(crear_token), json={"objetivo": "algo", "tipo": "HACKEAR"})
    assert r.status_code == 400 and r.headers["content-type"].startswith("application/problem+json")


def test_G1_sin_llm_configurado_lanzar_una_mision_es_503_y_no_crea_nada(crear_token: CrearToken) -> None:
    mundo = Mundo()
    r = _app(mundo, llm_configurado=False).post(
        "/misiones", headers=_h(crear_token), json={"objetivo": "algo"}
    )
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]


def test_G1_misiones_y_confirmaciones_inexistentes_son_404(crear_token: CrearToken) -> None:
    cliente = _app(Mundo())
    h = _h(crear_token)
    inexistente = "11111111-1111-4111-8111-111111111111"
    assert cliente.get(f"/misiones/{inexistente}", headers=h).status_code == 404
    assert cliente.post(f"/confirmaciones/{inexistente}/aprobar", headers=h).status_code == 404
    assert cliente.post(f"/confirmaciones/{inexistente}/rechazar", headers=h).status_code == 404


def test_G1_el_id_de_la_mision_debe_ser_un_uuid(crear_token: CrearToken) -> None:
    assert _app(Mundo()).get("/misiones/no-es-uuid", headers=_h(crear_token)).status_code == 400
