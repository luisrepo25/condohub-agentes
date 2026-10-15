from app.api.problemas import ProblemaError


def no_implementado(que: str) -> ProblemaError:
    """Los endpoints del contrato existen y ya están protegidos por rol.
    Su lógica llega en las fases 1 a 3."""
    return ProblemaError(501, "No implementado", f"{que} aún no está implementado", code="NO_IMPLEMENTADO")
