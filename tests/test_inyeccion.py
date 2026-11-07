"""Evidencia repetible contra inyección (SQL y de operadores de MongoDB) por la API real de Agentes.

Esperado: nunca un 5xx; un identificador se rechaza por su formato (UUID, 4xx); el texto libre se guarda
tal cual como dato; un objeto con operadores (`{"$gt": ""}`) donde va un texto se rechaza (422).
"""

import pytest

from tests.conftest import CrearToken
from tests.dobles_mision import LLMGuionado, Mundo, texto
from tests.test_mision_api import _app, _h

ATAQUES = [
    "' OR '1'='1",
    "'; DROP TABLE misiones; --",
    "x' UNION SELECT usename FROM pg_user --",
    '{"$gt": ""}',
    '" OR 1=1 --',
]


def _cliente():  # noqa: ANN202 - helper de prueba
    return _app(Mundo(LLMGuionado(*[texto("listo") for _ in ATAQUES * 2])))


@pytest.mark.parametrize("ataque", ATAQUES)
def test_los_ataques_en_el_identificador_se_rechazan_por_su_formato(
    crear_token: CrearToken, ataque: str
) -> None:
    cliente, h = _cliente(), _h(crear_token)

    respuestas = [
        cliente.get(f"/misiones/{ataque}", headers=h),
        cliente.post(f"/confirmaciones/{ataque}/aprobar", headers=h),
        cliente.post(f"/confirmaciones/{ataque}/rechazar", headers=h, json={"motivo": "x"}),
    ]
    assert all(r.status_code in (400, 404, 422) for r in respuestas)  # rechazo por formato, nunca un 5xx


@pytest.mark.parametrize("ataque", ATAQUES)
def test_el_objetivo_con_un_ataque_se_guarda_como_texto_y_la_mision_funciona(
    crear_token: CrearToken, ataque: str
) -> None:
    cliente, h = _cliente(), _h(crear_token)

    r = cliente.post("/misiones", headers=h, json={"objetivo": ataque})

    assert r.status_code == 202
    assert r.json()["objetivo"] == ataque
    assert cliente.get(f"/misiones/{r.json()['id']}", headers=h).status_code == 200


def test_un_objeto_con_operadores_donde_va_un_texto_se_rechaza(crear_token: CrearToken) -> None:
    cliente, h = _cliente(), _h(crear_token)

    for cuerpo in (
        {"objetivo": {"$gt": ""}},
        {"objetivo": "ok", "tipo": {"$ne": None}},
        {"objetivo": ["a", "b"]},
    ):
        assert cliente.post("/misiones", headers=h, json=cuerpo).status_code in (400, 422)


@pytest.mark.parametrize("ataque", ATAQUES)
def test_un_tipo_de_mision_con_un_ataque_es_400(crear_token: CrearToken, ataque: str) -> None:
    r = _cliente().post("/misiones", headers=_h(crear_token), json={"objetivo": "x", "tipo": ataque})

    assert r.status_code == 400
