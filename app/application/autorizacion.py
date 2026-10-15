from app.application.errores import SinPermiso
from app.domain.roles import Rol, Solicitante


def exigir_algun_rol(solicitante: Solicitante, *permitidos: Rol) -> None:
    """Autorización por rol del token: cada endpoint declara qué roles lo pueden usar."""
    if not solicitante.tiene_algun_rol(*permitidos):
        raise SinPermiso(f"Se requiere alguno de los roles: {', '.join(permitidos)}")
