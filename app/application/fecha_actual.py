"""Le da al LLM la fecha de hoy: sin ella adivina el día y el mes de «este fin de semana» o «el mes»."""

from datetime import datetime

_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def sistema_con_fecha(sistema: str, ahora: datetime) -> str:
    """Devuelve el prompt del sistema con la fecha de hoy (UTC) al final. No modifica el original."""
    hoy = f"Hoy es {_DIAS[ahora.weekday()]} {ahora.date().isoformat()} (UTC)."
    return f"{sistema}\n\n{hoy} Usa esta fecha para «hoy», «mañana», «este fin de semana» y «este mes»."
