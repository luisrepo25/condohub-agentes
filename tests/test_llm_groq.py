"""Adaptador del LLM (Groq, formato OpenAI) con transporte simulado: sin red ni clave real."""

import json
from typing import Any

import httpx
import pytest

from app.application.mision import LlamadaHerramienta, LLMNoDisponible, Mensaje
from app.infrastructure.llm.groq import LLMGroq
from tests.dobles_mision import Mundo


def _llm(
    respuesta: httpx.Response, capturas: list[dict[str, Any]] | None = None, clave: str = "k"
) -> LLMGroq:
    def manejador(p: httpx.Request) -> httpx.Response:
        if capturas is not None:
            capturas.append(
                {"cuerpo": json.loads(p.content), "auth": p.headers.get("Authorization"), "url": str(p.url)}
            )
        return respuesta

    return LLMGroq(clave, "modelo-x", cliente=httpx.Client(transport=httpx.MockTransport(manejador)))


def _ok(mensaje: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": mensaje}]})


HERRAMIENTAS = Mundo().catalogo.listar()


def test_G2_el_pedido_lleva_el_prompt_las_herramientas_y_la_clave() -> None:
    capturas: list[dict[str, Any]] = []
    _llm(_ok({"content": "hola"}), capturas).completar(
        "SISTEMA", [Mensaje("user", "Gestiona la morosidad")], HERRAMIENTAS
    )
    c = capturas[0]
    assert c["url"].endswith("/openai/v1/chat/completions") and c["auth"] == "Bearer k"
    cuerpo = c["cuerpo"]
    assert (
        cuerpo["messages"][0] == {"role": "system", "content": "SISTEMA"}
        and cuerpo["parallel_tool_calls"] is False
    )
    assert {t["function"]["name"] for t in cuerpo["tools"]} == {h.nombre for h in HERRAMIENTAS}
    assert all(t["function"]["parameters"]["type"] == "object" for t in cuerpo["tools"])


def test_G1_una_respuesta_de_texto_termina_la_mision() -> None:
    r = _llm(_ok({"content": "Resumen final"})).completar("S", [Mensaje("user", "x")], HERRAMIENTAS)
    assert r.texto == "Resumen final" and r.llamada is None


def test_G2_una_llamada_a_herramienta_se_interpreta() -> None:
    llamada = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "calcular_recargo", "arguments": '{"deudaVencida": "390.00"}'},
    }
    r = _llm(_ok({"content": None, "tool_calls": [llamada]})).completar(
        "S", [Mensaje("user", "x")], HERRAMIENTAS
    )
    assert (
        r.llamada == LlamadaHerramienta("call_1", "calcular_recargo", {"deudaVencida": "390.00"})
        and r.texto is None
    )


def test_G3_la_conversacion_se_serializa_en_el_formato_de_la_api() -> None:
    capturas: list[dict[str, Any]] = []
    mensajes = [
        Mensaje("user", "objetivo"),
        Mensaje("assistant", llamada=LlamadaHerramienta("c1", "consultar_morosos", {})),
        Mensaje("tool", '{"total": 2}', llamada_id="c1"),
        Mensaje("assistant", "pensando"),
    ]
    _llm(_ok({"content": "ok"}), capturas).completar("S", mensajes, HERRAMIENTAS)
    enviados = capturas[0]["cuerpo"]["messages"][1:]
    assert enviados[1]["tool_calls"][0] == {
        "id": "c1",
        "type": "function",
        "function": {"name": "consultar_morosos", "arguments": "{}"},
    }
    assert enviados[2] == {"role": "tool", "tool_call_id": "c1", "content": '{"total": 2}'}
    assert enviados[3] == {"role": "assistant", "content": "pensando"}


@pytest.mark.parametrize(
    "respuesta",
    [
        httpx.Response(401),
        httpx.Response(503),
        httpx.Response(200, text="no es json"),
        httpx.Response(200, json={"choices": []}),
        _ok({"tool_calls": [{"id": "c", "function": {"name": "x", "arguments": "{no json"}}]}),
        _ok({"tool_calls": [{"id": "c", "function": {"name": "x", "arguments": "[1]"}}]}),
    ],
)
def test_G1_cualquier_respuesta_inutilizable_es_llm_no_disponible(respuesta: httpx.Response) -> None:
    with pytest.raises(LLMNoDisponible):
        _llm(respuesta).completar("S", [Mensaje("user", "x")], HERRAMIENTAS)


def test_G1_sin_clave_no_se_llama_al_llm() -> None:
    capturas: list[dict[str, Any]] = []
    with pytest.raises(LLMNoDisponible, match="GROQ_API_KEY"):
        _llm(_ok({"content": "x"}), capturas, clave="").completar("S", [Mensaje("user", "x")], HERRAMIENTAS)
    assert capturas == []


def test_G1_sin_conexion_es_llm_no_disponible() -> None:
    def cae(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    llm = LLMGroq("k", "m", cliente=httpx.Client(transport=httpx.MockTransport(cae)))
    with pytest.raises(LLMNoDisponible):
        llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS)


# --- Límite de uso (429) y cortes (5xx): se reintenta con espera y se respeta Retry-After ---


def _llm_con_respuestas(respuestas: list[httpx.Response], esperas: list[float]) -> tuple[LLMGroq, list[int]]:
    cola, llamadas = list(respuestas), [0]

    def manejador(_: httpx.Request) -> httpx.Response:
        llamadas[0] += 1
        return cola.pop(0)

    llm = LLMGroq(
        "k", "m", cliente=httpx.Client(transport=httpx.MockTransport(manejador)), dormir=esperas.append
    )
    return llm, llamadas


def test_G1_un_429_se_reintenta_y_respeta_retry_after() -> None:
    esperas: list[float] = []
    llm, llamadas = _llm_con_respuestas(
        [httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(429), _ok({"content": "listo"})],
        esperas,
    )
    assert llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS).texto == "listo"
    assert llamadas[0] == 3 and esperas == [3.0, 2.0]  # Retry-After; sin él, exponencial (2**1)


def test_G1_un_503_tambien_se_reintenta() -> None:
    esperas: list[float] = []
    llm, llamadas = _llm_con_respuestas([httpx.Response(503), _ok({"content": "ok"})], esperas)
    assert llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS).texto == "ok" and llamadas[0] == 2


def test_G1_si_el_limite_no_cede_se_rinde_tras_4_intentos() -> None:
    esperas: list[float] = []
    llm, llamadas = _llm_con_respuestas([httpx.Response(429)] * 4, esperas)
    with pytest.raises(LLMNoDisponible, match="429"):
        llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS)
    assert llamadas[0] == 4 and len(esperas) == 3


def test_G1_la_espera_nunca_pasa_de_30_segundos() -> None:
    esperas: list[float] = []
    llm, _ = _llm_con_respuestas(
        [httpx.Response(429, headers={"retry-after": "600"}), _ok({"content": "x"})], esperas
    )
    llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS)
    assert esperas == [30.0]


@pytest.mark.parametrize("codigo", [400, 401, 403, 404])
def test_G1_los_errores_del_cliente_no_se_reintentan(codigo: int) -> None:
    esperas: list[float] = []
    llm, llamadas = _llm_con_respuestas([httpx.Response(codigo), _ok({"content": "x"})], esperas)
    with pytest.raises(LLMNoDisponible):
        llm.completar("S", [Mensaje("user", "x")], HERRAMIENTAS)
    assert llamadas[0] == 1 and esperas == []
