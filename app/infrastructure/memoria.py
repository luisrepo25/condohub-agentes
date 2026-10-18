"""Repositorios en memoria del monitoreo (`PERSISTENCIA=memoria`: se pierden al reiniciar)."""

from app.domain.monitoreo import Informe, Metricas


class MetricasEnMemoria:
    def __init__(self) -> None:
        self._lecturas: list[Metricas] = []

    def guardar(self, metricas: Metricas) -> None:
        self._lecturas.append(metricas)

    def ultimas(self, cantidad: int) -> list[Metricas]:
        return list(self._lecturas[-cantidad:]) if cantidad > 0 else []


class InformesEnMemoria:
    def __init__(self) -> None:
        self._informes: list[Informe] = []

    def guardar(self, informe: Informe) -> None:
        self._informes.append(informe)

    def ultimos(self, cantidad: int) -> list[Informe]:
        return list(reversed(self._informes))[:cantidad]
