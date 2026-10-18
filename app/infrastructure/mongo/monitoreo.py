"""Repositorios MongoDB del monitoreo (colecciones `metricas` e `informes` de `db/mongo-init.js`).

El dinero se guarda como `Decimal128` (F10); las fechas, en UTC (cliente creado con `tz_aware=True`).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from bson.decimal128 import Decimal128
from pymongo.database import Database

from app.domain.monitoreo import Alerta, Informe, Metricas, Origen, Severidad, TipoAnomalia


def _utc(fecha: datetime) -> datetime:
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=UTC)


def _a_doc_metricas(m: Metricas) -> dict[str, Any]:
    return {
        "generadaEn": m.generadas_en,
        "unidadesMorosas": m.unidades_morosas,
        "deudaVencida": Decimal128(m.deuda_vencida),
        "pagosPendientes": m.pagos_pendientes,
        "diasPagoMasAntiguo": m.dias_pago_mas_antiguo,
    }


def _de_doc_metricas(d: dict[str, Any]) -> Metricas:
    return Metricas(
        generadas_en=_utc(d["generadaEn"]),
        unidades_morosas=int(d["unidadesMorosas"]),
        deuda_vencida=d["deudaVencida"].to_decimal()
        if isinstance(d["deudaVencida"], Decimal128)
        else Decimal(str(d["deudaVencida"])),
        pagos_pendientes=int(d["pagosPendientes"]),
        dias_pago_mas_antiguo=d.get("diasPagoMasAntiguo"),
    )


class MetricasMongo:
    def __init__(self, base: Database[dict[str, Any]]) -> None:
        self._col = base["metricas"]

    def guardar(self, metricas: Metricas) -> None:
        self._col.insert_one(_a_doc_metricas(metricas))

    def ultimas(self, cantidad: int) -> list[Metricas]:
        if cantidad <= 0:
            return []
        docs = list(self._col.find().sort("generadaEn", -1).limit(cantidad))
        return [_de_doc_metricas(d) for d in reversed(docs)]


class InformesMongo:
    def __init__(self, base: Database[dict[str, Any]]) -> None:
        self._col = base["informes"]

    def guardar(self, i: Informe) -> None:
        self._col.insert_one(
            {
                "informeId": str(i.id),
                "generadoEn": i.generado_en,
                "origen": i.origen.value,
                "metricas": _a_doc_metricas(i.metricas),
                "alertas": [
                    {
                        "tipo": a.tipo.value,
                        "severidad": a.severidad.value,
                        "mensaje": a.mensaje,
                        "valor": a.valor,
                        "referencia": a.referencia,
                    }
                    for a in i.alertas
                ],
                "resumen": i.resumen,
                "lineaBase": i.linea_base,
                "notificado": i.notificado,
            }
        )

    def ultimos(self, cantidad: int) -> list[Informe]:
        if cantidad <= 0:
            return []
        return [self._a_informe(d) for d in self._col.find().sort("generadoEn", -1).limit(cantidad)]

    @staticmethod
    def _a_informe(d: dict[str, Any]) -> Informe:
        return Informe(
            id=UUID(d["informeId"]),
            generado_en=_utc(d["generadoEn"]),
            origen=Origen(d["origen"]),
            metricas=_de_doc_metricas(d["metricas"]),
            alertas=tuple(
                Alerta(
                    TipoAnomalia(a["tipo"]),
                    Severidad(a["severidad"]),
                    a["mensaje"],
                    a["valor"],
                    a["referencia"],
                )
                for a in d["alertas"]
            ),
            resumen=d["resumen"],
            linea_base=bool(d["lineaBase"]),
            notificado=bool(d["notificado"]),
        )
