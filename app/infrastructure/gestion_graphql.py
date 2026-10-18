"""Habilidades de solo lectura del agente sobre Gestión (GraphQL). Solo `query`: nunca mutations (G5, G2)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.application.herramientas import EstadoCuentaDato
from app.application.monitoreo import GestionNoDisponible, MorosoDato, PagoPendienteDato

CONSULTA_MOROSOS = "{ morosos { unidadId deudaVencida expensasVencidas } }"
CONSULTA_PAGOS_PENDIENTES = "{ pagosPendientes { id monto fechaPago } }"
CONSULTA_ESTADO_DE_CUENTA = (
    "query($unidadId: ID!) { estadoDeCuenta(unidadId: $unidadId) "
    "{ unidadId codigo bloque deudaTotal deudaVencida expensasVencidas saldoAFavor moroso } }"
)


class GestionGraphQL:
    def __init__(
        self, url: str, token: Callable[[], str], cliente: httpx.Client | None = None, tiempo_s: float = 20.0
    ) -> None:
        self._url = url
        self._token = token
        self._cliente = cliente or httpx.Client(timeout=tiempo_s)

    def _consultar(self, consulta: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            r = self._cliente.post(
                self._url,
                json={"query": consulta, "variables": variables or {}},
                headers={"Authorization": f"Bearer {self._token()}"},
            )
        except httpx.HTTPError as e:
            raise GestionNoDisponible("No se pudo conectar con Gestión") from e
        if r.status_code != 200:
            raise GestionNoDisponible(f"Gestión respondió HTTP {r.status_code}")
        try:
            cuerpo: dict[str, Any] = r.json()
        except ValueError as e:
            raise GestionNoDisponible("Gestión no devolvió JSON") from e
        if cuerpo.get("errors"):
            raise GestionNoDisponible(str(cuerpo["errors"][0].get("message", "Error de Gestión")))
        datos = cuerpo.get("data")
        if not isinstance(datos, dict):
            raise GestionNoDisponible("Gestión no devolvió datos")
        return datos

    def morosos(self) -> list[MorosoDato]:
        try:
            return [
                MorosoDato(str(m["unidadId"]), Decimal(m["deudaVencida"]), int(m["expensasVencidas"]))
                for m in self._consultar(CONSULTA_MOROSOS)["morosos"]
            ]
        except (KeyError, TypeError, ValueError, InvalidOperation) as e:
            raise GestionNoDisponible("Respuesta de morosos con forma inesperada") from e

    def pagos_pendientes(self) -> list[PagoPendienteDato]:
        try:
            return [
                PagoPendienteDato(str(p["id"]), Decimal(p["monto"]), date.fromisoformat(p["fechaPago"]))
                for p in self._consultar(CONSULTA_PAGOS_PENDIENTES)["pagosPendientes"]
            ]
        except (KeyError, TypeError, ValueError, InvalidOperation) as e:
            raise GestionNoDisponible("Respuesta de pagos pendientes con forma inesperada") from e

    def estado_de_cuenta(self, unidad_id: str) -> EstadoCuentaDato:
        try:
            e = self._consultar(CONSULTA_ESTADO_DE_CUENTA, {"unidadId": unidad_id})["estadoDeCuenta"]
            return EstadoCuentaDato(
                str(e["unidadId"]),
                str(e["codigo"]),
                str(e["bloque"]),
                Decimal(e["deudaTotal"]),
                Decimal(e["deudaVencida"]),
                int(e["expensasVencidas"]),
                Decimal(e["saldoAFavor"]),
                bool(e["moroso"]),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as e:
            raise GestionNoDisponible("Respuesta de estado de cuenta con forma inesperada") from e
