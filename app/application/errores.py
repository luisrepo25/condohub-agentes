class TokenInvalido(Exception):
    """El token falta, está mal firmado, venció o no es del emisor esperado."""


class ServicioDeIdentidadNoDisponible(Exception):
    """No se pudieron obtener las claves de firma de Keycloak."""


class SinPermiso(Exception):
    """El rol del solicitante no puede usar la operación."""
