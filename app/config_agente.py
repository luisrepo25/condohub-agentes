"""Configuración del agente de misiones (G1-G3, F5). Parámetros de negocio y secretos: solo variables de
entorno."""

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ConfigAgente:
    groq_api_key: str
    groq_modelo: str
    groq_url_base: str
    limite_pasos: int
    recargo_mensual: Decimal
    n8n_webhook_recordatorios: str
    reservas_url: str = ""

    @classmethod
    def desde_entorno(cls) -> "ConfigAgente":
        e = os.environ
        return cls(
            groq_api_key=e.get("GROQ_API_KEY", ""),
            groq_modelo=e.get("GROQ_MODELO", "openai/gpt-oss-120b"),
            groq_url_base=e.get("GROQ_URL_BASE", "https://api.groq.com/openai"),
            limite_pasos=int(e.get("MISION_LIMITE_PASOS", 15)),
            recargo_mensual=Decimal(e.get("RECARGO_MENSUAL", "0.02")),  # F5: 2 % mensual simple (parámetro)
            n8n_webhook_recordatorios=e.get("N8N_WEBHOOK_RECORDATORIOS", ""),
            reservas_url=e.get("RESERVAS_URL", ""),  # sin ella el agente no ve Reservas
        )

    @property
    def llm_configurado(self) -> bool:
        return bool(self.groq_api_key)
