"""consultar_reservas con filtros nulos (G1, G2).

Groq rechaza la llamada con HTTP 400 `tool_use_failed` cuando el modelo manda `"estado": null` o
`"unidadId": null` y el esquema solo admite texto: el 07/11/2026 la misión «¿Qué reservas hay este
fin de semana?» terminó en ERROR por eso. Un filtro nulo significa «sin filtro».
"""

from jsonschema import Draft202012Validator

from app.application.herramientas_reservas import HERRAMIENTAS_RESERVAS, CatalogoConReservas
from tests.dobles_mision import Mundo
from tests.test_herramientas_reservas import ReservasFalsas, _reserva


def _consultar():
    return next(h for h in HERRAMIENTAS_RESERVAS if h.nombre == "consultar_reservas")


def test_consultar_reservas_acepta_null_en_los_filtros_del_esquema():
    validador = Draft202012Validator(_consultar().parametros)

    assert not list(validador.iter_errors({"estado": None, "unidadId": None}))
    assert not list(validador.iter_errors({}))
    assert not list(validador.iter_errors({"estado": "CONFIRMADA", "unidadId": "u1"}))


def test_consultar_reservas_sigue_rechazando_un_estado_inventado_en_el_esquema():
    validador = Draft202012Validator(_consultar().parametros)

    assert list(validador.iter_errors({"estado": "INVENTADO"}))


def test_consultar_reservas_trata_null_como_sin_filtro():
    reservas = ReservasFalsas(
        [
            _reserva("r1", "CONFIRMADA", "2026-11-14T14:00:00Z", "u1"),
            _reserva("r2", "CANCELADA", "2026-11-15T14:00:00Z", "u2"),
        ]
    )
    catalogo = CatalogoConReservas(Mundo().catalogo, reservas)

    r = catalogo.ejecutar("consultar_reservas", {"estado": None, "unidadId": None})

    assert r["total"] == 2
    assert reservas.pedidos == [(None, None)]


def test_consultar_reservas_con_un_estado_real_sigue_filtrando():
    reservas = ReservasFalsas(
        [
            _reserva("r1", "CONFIRMADA", "2026-11-14T14:00:00Z"),
            _reserva("r2", "CANCELADA", "2026-11-15T14:00:00Z"),
        ]
    )
    catalogo = CatalogoConReservas(Mundo().catalogo, reservas)

    r = catalogo.ejecutar("consultar_reservas", {"estado": "CONFIRMADA", "unidadId": None})

    assert r["total"] == 1
    assert reservas.pedidos == [(None, "CONFIRMADA")]
