"""Quién hace la petición. Dominio puro: sin FastAPI, JWT ni librerías de ML."""

from dataclasses import dataclass
from enum import StrEnum


class Rol(StrEnum):
    """Roles del realm `condohub` de Keycloak. No hay otros."""

    ADMIN = "ADMIN"
    RESIDENTE = "RESIDENTE"
    GUARDIA = "GUARDIA"


@dataclass(frozen=True)
class Solicitante:
    """El `sub` del token de Keycloak y sus roles."""

    sub: str
    roles: frozenset[Rol]

    def tiene_algun_rol(self, *permitidos: Rol) -> bool:
        return any(rol in self.roles for rol in permitidos)
