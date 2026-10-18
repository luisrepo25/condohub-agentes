"""Esquemas del monitoreo (G5): camelCase como en `agentes.yaml`; dinero como string decimal (F10)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.monitoreo import Alerta, Informe, Metricas


class MetricasSchema(BaseModel):
    unidadesMorosas: int
    deudaVencida: str
    pagosPendientes: int
    diasPagoMasAntiguo: int | None = None

    @classmethod
    def desde_dominio(cls, m: Metricas) -> "MetricasSchema":
        return cls(
            unidadesMorosas=m.unidades_morosas,
            deudaVencida=f"{m.deuda_vencida:.2f}",
            pagosPendientes=m.pagos_pendientes,
            diasPagoMasAntiguo=m.dias_pago_mas_antiguo,
        )


class AlertaSchema(BaseModel):
    tipo: str
    severidad: str
    mensaje: str
    valor: str
    referencia: str

    @classmethod
    def desde_dominio(cls, a: Alerta) -> "AlertaSchema":
        return cls(
            tipo=a.tipo.value,
            severidad=a.severidad.value,
            mensaje=a.mensaje,
            valor=a.valor,
            referencia=a.referencia,
        )


class InformeMonitoreo(BaseModel):
    id: UUID
    generadoEn: datetime
    origen: str
    metricas: MetricasSchema
    alertas: list[AlertaSchema]
    resumen: str
    lineaBase: bool
    notificado: bool

    @classmethod
    def desde_dominio(cls, i: Informe) -> "InformeMonitoreo":
        return cls(
            id=i.id,
            generadoEn=i.generado_en,
            origen=i.origen.value,
            metricas=MetricasSchema.desde_dominio(i.metricas),
            alertas=[AlertaSchema.desde_dominio(a) for a in i.alertas],
            resumen=i.resumen,
            lineaBase=i.linea_base,
            notificado=i.notificado,
        )
