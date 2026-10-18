"""LLM del agente en Groq (API compatible con OpenAI, con llamadas a herramientas; sin SDK). La clave:
GROQ_API_KEY."""

import json
from typing import Any

import httpx

from app.application.herramientas import Herramienta
from app.application.mision import LlamadaHerramienta, LLMNoDisponible, Mensaje, RespuestaLLM


def _mensaje_api(m: Mensaje) -> dict[str, Any]:
    if m.rol == "tool":
        return {"role": "tool", "tool_call_id": m.llamada_id, "content": m.contenido or ""}
    if m.llamada is not None:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": m.llamada.id,
                    "type": "function",
                    "function": {
                        "name": m.llamada.nombre,
                        "arguments": json.dumps(m.llamada.argumentos, ensure_ascii=False),
                    },
                }
            ],
        }
    return {"role": m.rol, "content": m.contenido or ""}


class LLMGroq:
    def __init__(
        self,
        api_key: str,
        modelo: str,
        url_base: str = "https://api.groq.com/openai",
        cliente: httpx.Client | None = None,
        tiempo_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._modelo = modelo
        self._url_base = url_base.rstrip("/")
        self._cliente = cliente or httpx.Client(timeout=tiempo_s)

    def completar(
        self, sistema: str, mensajes: list[Mensaje], herramientas: list[Herramienta]
    ) -> RespuestaLLM:
        if not self._api_key:
            raise LLMNoDisponible("El LLM no está configurado (falta GROQ_API_KEY)")
        cuerpo = {
            "model": self._modelo,
            "temperature": 0,
            "messages": [{"role": "system", "content": sistema}, *[_mensaje_api(m) for m in mensajes]],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": h.nombre, "description": h.descripcion, "parameters": h.parametros},
                }
                for h in herramientas
            ],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        }
        try:
            r = self._cliente.post(
                f"{self._url_base}/v1/chat/completions",
                json=cuerpo,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as e:
            raise LLMNoDisponible("No se pudo conectar con el LLM") from e
        if r.status_code != 200:
            raise LLMNoDisponible(f"El LLM respondió HTTP {r.status_code}")
        try:
            mensaje = r.json()["choices"][0]["message"]
            llamadas = mensaje.get("tool_calls") or []
            contenido = mensaje.get("content")
            texto = str(contenido) if contenido else None
            if not llamadas:
                return RespuestaLLM(texto=texto)
            primera = llamadas[0]
            argumentos = json.loads(primera["function"]["arguments"] or "{}")
            if not isinstance(argumentos, dict):
                raise ValueError("los argumentos no son un objeto")
            return RespuestaLLM(
                texto=texto,
                llamada=LlamadaHerramienta(str(primera["id"]), str(primera["function"]["name"]), argumentos),
            )
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise LLMNoDisponible("El LLM no devolvió una respuesta utilizable") from e
