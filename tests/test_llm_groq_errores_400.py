"""Errores 400 de Groq (G1): se reintenta la generación fallida y el motivo real queda en el error.

El 07/11/2026 una misión terminó en ERROR con «El LLM respondió HTTP 400» sin más datos: Groq responde
400 `tool_use_failed` cuando el modelo genera una llamada a herramienta que no cumple el esquema. Es
intermitente: repetir la misma llamada funciona.
"""

from typing import Any

import httpx
import pytest

from app.application.mision import LLMNoDisponible, Mensaje
from app.infrastructure.llm.groq import LLMGroq
from tests.dobles_mision import Mundo

HERRAMIENTAS = Mundo().catalogo.listar()
FALLO_DE_GENERACION = {
    "error": {
        "message": "Tool call validation failed: parameters for tool consultar_reservas did not match schema",
        "type": "invalid_request_error",
        "code": "tool_use_failed",
        "failed_generation": '{"name": "consultar_reservas"}',
    }
}


def _llm(respuestas: list[httpx.Response]) -> tuple[LLMGroq, list[float]]:
    pendientes = list(respuestas)
    esperas: list[float] = []

    def manejador(_: httpx.Request) -> httpx.Response:
        return pendientes.pop(0) if len(pendientes) > 1 else pendientes[0]

    cliente = httpx.Client(transport=httpx.MockTransport(manejador))
    return LLMGroq("k", "modelo-x", cliente=cliente, dormir=esperas.append), esperas


def _ok(mensaje: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": mensaje}]})


def test_G1_una_generacion_fallida_tool_use_failed_se_reintenta_y_la_mision_sigue() -> None:
    llm, esperas = _llm([httpx.Response(400, json=FALLO_DE_GENERACION), _ok({"content": "listo"})])

    respuesta = llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS)

    assert respuesta.texto == "listo"
    assert len(esperas) == 1


def test_G1_si_la_generacion_sigue_fallando_el_error_trae_el_motivo_de_groq() -> None:
    llm, _ = _llm([httpx.Response(400, json=FALLO_DE_GENERACION)])

    with pytest.raises(LLMNoDisponible) as e:
        llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS)

    texto = str(e.value)
    assert "HTTP 400" in texto and "tool_use_failed" in texto and "consultar_reservas" in texto
    assert "failed_generation" not in texto


def test_G1_un_400_que_no_es_de_generacion_no_se_reintenta_pero_dice_por_que() -> None:
    cuerpo = {"error": {"message": "Invalid request: model not found", "code": "model_not_found"}}
    llm, esperas = _llm([httpx.Response(400, json=cuerpo)])

    with pytest.raises(LLMNoDisponible) as e:
        llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS)

    assert esperas == []
    assert "HTTP 400" in str(e.value) and "model_not_found" in str(e.value)


def test_G1_un_error_sin_cuerpo_json_sigue_mostrando_solo_el_codigo() -> None:
    llm, _ = _llm([httpx.Response(401, text="nope")])

    with pytest.raises(LLMNoDisponible) as e:
        llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS)

    assert str(e.value) == "El LLM respondió HTTP 401"
