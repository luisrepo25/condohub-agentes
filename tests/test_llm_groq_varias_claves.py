"""G1: varias claves de Groq (GROQ_API_KEY=k1,k2,k3): si una se agota o la rechazan, se usa otra."""

import httpx
import pytest

from app.application.mision import LLMNoDisponible, Mensaje
from app.infrastructure.llm.groq import LLMGroq
from tests.dobles_mision import Mundo

HERRAMIENTAS = Mundo().catalogo.listar()
OK = httpx.Response(200, json={"choices": [{"message": {"content": "listo"}}]})


def _llm(
    clave: str, respuestas: dict[str, int], usadas: list[str], esperas: list[float] | None = None
) -> LLMGroq:
    """`respuestas` dice qué código devuelve cada clave (200 si no figura)."""

    def manejador(p: httpx.Request) -> httpx.Response:
        clave_usada = p.headers["Authorization"].removeprefix("Bearer ")
        usadas.append(clave_usada)
        codigo = respuestas.get(clave_usada, 200)
        return OK if codigo == 200 else httpx.Response(codigo)

    sin_esperar = (lambda s: esperas.append(s)) if esperas is not None else (lambda s: None)
    return LLMGroq(
        clave, "m", cliente=httpx.Client(transport=httpx.MockTransport(manejador)), dormir=sin_esperar
    )


def _completar(llm: LLMGroq) -> str | None:
    return llm.completar("S", [Mensaje("user", "hola")], HERRAMIENTAS).texto


def test_G1_si_la_primera_clave_agota_su_limite_se_usa_la_segunda_sin_esperar() -> None:
    usadas: list[str] = []
    esperas: list[float] = []

    assert _completar(_llm("k1,k2", {"k1": 429}, usadas, esperas)) == "listo"

    assert usadas == ["k1", "k2"]
    assert esperas == []


def test_G1_la_clave_que_funciona_se_recuerda_para_las_llamadas_siguientes() -> None:
    usadas: list[str] = []
    llm = _llm("k1,k2", {"k1": 429}, usadas)

    _completar(llm)
    _completar(llm)

    assert usadas == ["k1", "k2", "k2"]


def test_G1_una_clave_rechazada_con_401_tambien_pasa_a_la_siguiente() -> None:
    usadas: list[str] = []

    assert _completar(_llm("k1, k2", {"k1": 401}, usadas)) == "listo"
    assert usadas == ["k1", "k2"]


def test_G1_si_todas_las_claves_estan_agotadas_espera_y_al_final_avisa_que_no_hay_LLM() -> None:
    usadas: list[str] = []
    esperas: list[float] = []

    with pytest.raises(LLMNoDisponible):
        _completar(_llm("k1,k2", {"k1": 429, "k2": 429}, usadas, esperas))

    assert set(usadas) == {"k1", "k2"} and len(esperas) == 3


def test_G1_con_una_sola_clave_todo_sigue_igual() -> None:
    usadas: list[str] = []

    assert _completar(_llm("k1", {}, usadas)) == "listo"
    assert usadas == ["k1"]


def test_G1_sin_claves_el_LLM_no_esta_disponible() -> None:
    with pytest.raises(LLMNoDisponible):
        _completar(_llm(" , ", {}, []))
