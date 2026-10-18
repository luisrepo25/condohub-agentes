"""Casos de uso de las misiones (G1-G3, F5): el agente razona con un LLM y actúa solo por el catálogo de
herramientas.

Regla de oro (G2): lo que no es lectura no se ejecuta al pedirlo; queda como `ConfirmacionPendiente` hasta
que un ADMIN
identificado lo aprueba. Cada paso queda en la bitácora (G3) y la conversación se reconstruye desde ella al
reanudar.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.application.herramientas import CatalogoHerramientas, Herramienta
from app.application.prompt_mision import SISTEMA
from app.domain.mision import (
    ConfirmacionPendiente,
    EstadoConfirmacion,
    EstadoMision,
    Mision,
    PasoBitacora,
    Riesgo,
    TipoMision,
    TipoPaso,
)


class MisionNoEncontrada(Exception):
    pass


class ConfirmacionNoEncontrada(Exception):
    pass


class ConflictoDeVersion(Exception):
    """Otro proceso cambió la confirmación mientras se resolvía (bloqueo optimista)."""


class LLMNoDisponible(Exception):
    """El LLM no responde, no está configurado o devolvió algo que no se puede interpretar."""


class ArgumentosInvalidos(Exception):
    """La solicitud de una herramienta no cumple su esquema."""


class Reloj(Protocol):
    def ahora(self) -> datetime: ...


@dataclass(frozen=True)
class LlamadaHerramienta:
    id: str
    nombre: str
    argumentos: dict[str, Any]


@dataclass(frozen=True)
class Mensaje:
    rol: str  # "user" | "assistant" | "tool"
    contenido: str | None = None
    llamada: LlamadaHerramienta | None = None  # assistant que pide una herramienta
    llamada_id: str | None = None  # tool: a qué llamada responde


@dataclass(frozen=True)
class RespuestaLLM:
    texto: str | None = None
    llamada: LlamadaHerramienta | None = None


class LLMPort(Protocol):
    def completar(
        self, sistema: str, mensajes: list[Mensaje], herramientas: list[Herramienta]
    ) -> RespuestaLLM:
        """Una vuelta del modelo. Lanza `LLMNoDisponible`."""
        ...


class MisionRepository(Protocol):
    def guardar(self, mision: Mision) -> None: ...

    def obtener(self, mision_id: UUID) -> Mision | None: ...


class ConfirmacionRepository(Protocol):
    def guardar(self, confirmacion: ConfirmacionPendiente) -> None:
        """Inserta si es nueva; si existe, exige que nadie la haya cambiado antes (`ConflictoDeVersion`)."""
        ...

    def obtener(self, confirmacion_id: UUID) -> ConfirmacionPendiente | None: ...

    def de_mision(self, mision_id: UUID) -> list[ConfirmacionPendiente]: ...


class BitacoraRepository(Protocol):
    def agregar(self, paso: PasoBitacora) -> None: ...

    def listar(self, mision_id: UUID) -> list[PasoBitacora]:
        """En orden de ejecución."""
        ...


class _Base:
    def __init__(
        self,
        misiones: MisionRepository,
        confirmaciones: ConfirmacionRepository,
        bitacora: BitacoraRepository,
        reloj: Reloj,
    ) -> None:
        self._misiones = misiones
        self._confirmaciones = confirmaciones
        self._bitacora = bitacora
        self._reloj = reloj

    def _mision(self, mision_id: UUID) -> Mision:
        mision = self._misiones.obtener(mision_id)
        if mision is None:
            raise MisionNoEncontrada(str(mision_id))
        return mision

    def _registrar(self, mision_id: UUID, tipo: TipoPaso, **campos: Any) -> None:
        numero = len(self._bitacora.listar(mision_id)) + 1
        self._bitacora.agregar(PasoBitacora(mision_id, numero, tipo, self._reloj.ahora(), **campos))


def reconstruir_conversacion(mision: Mision, pasos: list[PasoBitacora]) -> list[Mensaje]:
    """La conversación con el LLM sale de la bitácora: sobrevive a un reinicio y a la espera del ADMIN."""
    mensajes = [Mensaje("user", mision.objetivo)]
    for p in pasos:
        if p.tipo is TipoPaso.RAZONAMIENTO and p.salida:
            mensajes.append(Mensaje("assistant", str(p.salida.get("texto", ""))))
        elif p.tipo is TipoPaso.LLAMADA_HERRAMIENTA and p.herramienta and p.llamada_id:
            mensajes.append(
                Mensaje("assistant", llamada=LlamadaHerramienta(p.llamada_id, p.herramienta, p.entrada or {}))
            )
        elif p.tipo is TipoPaso.RESULTADO_HERRAMIENTA and p.llamada_id:
            mensajes.append(
                Mensaje("tool", json.dumps(p.salida or {}, ensure_ascii=False), llamada_id=p.llamada_id)
            )
    return mensajes


class IniciarMision(_Base):
    def iniciar(
        self, admin_sub: str, tipo: TipoMision, objetivo: str, limite_pasos: int, con_llm: bool = True
    ) -> Mision:
        mision = Mision.nueva(tipo, objetivo, admin_sub, self._reloj.ahora(), limite_pasos, con_llm)
        self._misiones.guardar(mision)
        return mision


class EjecutarMision(_Base):
    """El bucle del agente: LLM → herramienta → resultado → LLM, hasta terminar, llegar al límite o esperar
    al ADMIN."""

    def __init__(
        self,
        misiones: MisionRepository,
        confirmaciones: ConfirmacionRepository,
        bitacora: BitacoraRepository,
        reloj: Reloj,
        catalogo: CatalogoHerramientas,
        llm: LLMPort,
    ) -> None:
        super().__init__(misiones, confirmaciones, bitacora, reloj)
        self._catalogo = catalogo
        self._llm = llm

    def ejecutar(self, mision_id: UUID) -> Mision:
        mision = self._mision(mision_id)
        if mision.estado is not EstadoMision.EN_CURSO or not mision.con_llm:
            return mision
        try:
            self._bucle(mision)
        except Exception as e:  # p. ej. la base de datos: la misión no se queda «en curso» para siempre
            if mision.estado is EstadoMision.EN_CURSO:
                self._registrar(mision.id, TipoPaso.ERROR, salida={"error": f"Error inesperado: {e}"})
                mision.fallar(f"Error inesperado: {e}", self._reloj.ahora())
        self._misiones.guardar(mision)
        return mision

    def _bucle(self, mision: Mision) -> None:
        mensajes = reconstruir_conversacion(mision, self._bitacora.listar(mision.id))
        while mision.estado is EstadoMision.EN_CURSO:
            if mision.alcanzo_el_limite:
                motivo = f"Se alcanzó el límite de {mision.limite_pasos} pasos sin terminar."
                self._registrar(mision.id, TipoPaso.FIN, salida={"motivo": motivo})
                mision.marcar_incompleta(motivo, self._reloj.ahora())
                break
            try:
                respuesta = self._llm.completar(SISTEMA, mensajes, self._catalogo.listar())
            except LLMNoDisponible as e:
                self._registrar(mision.id, TipoPaso.ERROR, salida={"error": str(e)})
                mision.fallar(f"El LLM no respondió: {e}", self._reloj.ahora())
                break
            mision.registrar_paso()
            if respuesta.texto and respuesta.texto.strip():
                self._registrar(mision.id, TipoPaso.RAZONAMIENTO, salida={"texto": respuesta.texto})
                mensajes.append(Mensaje("assistant", respuesta.texto))
            if respuesta.llamada is None:
                resumen = (respuesta.texto or "La misión terminó sin resumen.").strip()
                self._registrar(mision.id, TipoPaso.FIN, salida={"resumen": resumen})
                mision.completar(resumen, self._reloj.ahora())
                break
            self._atender(mision, respuesta.llamada, mensajes)

    def _atender(self, mision: Mision, llamada: LlamadaHerramienta, mensajes: list[Mensaje]) -> None:
        herramienta = self._catalogo.obtener(llamada.nombre)
        self._registrar(
            mision.id,
            TipoPaso.LLAMADA_HERRAMIENTA,
            herramienta=llamada.nombre,
            entrada=llamada.argumentos,
            llamada_id=llamada.id,
        )
        mensajes.append(Mensaje("assistant", llamada=llamada))
        try:
            if herramienta is None:
                raise ValueError(f"Herramienta desconocida: {llamada.nombre}")
            self._catalogo.validar(llamada.nombre, llamada.argumentos)
            if herramienta.riesgo is not Riesgo.LECTURA:
                if self._ya_rechazada(mision, herramienta, llamada):
                    raise ValueError(
                        f"El ADMIN ya rechazó «{herramienta.nombre}» para esa unidad en esta misión: "
                        "no insistas."
                    )
                self._pedir_confirmacion(mision, herramienta, llamada)
                return
            salida = self._catalogo.ejecutar(llamada.nombre, llamada.argumentos)
        except Exception as e:  # el error vuelve al LLM como resultado de la herramienta
            salida = {"error": str(e)}
        self._registrar(
            mision.id,
            TipoPaso.RESULTADO_HERRAMIENTA,
            herramienta=llamada.nombre,
            salida=salida,
            llamada_id=llamada.id,
        )
        mensajes.append(Mensaje("tool", json.dumps(salida, ensure_ascii=False), llamada_id=llamada.id))

    def _ya_rechazada(self, mision: Mision, herramienta: Herramienta, llamada: LlamadaHerramienta) -> bool:
        """Un ADMIN ya rechazó esta acción para esta unidad: no se le vuelve a preguntar en la misión."""
        unidad = llamada.argumentos.get("unidadId")
        return any(
            c.herramienta == herramienta.nombre
            and c.estado is EstadoConfirmacion.RECHAZADA
            and c.argumentos.get("unidadId") == unidad
            for c in self._confirmaciones.de_mision(mision.id)
        )

    def _pedir_confirmacion(
        self, mision: Mision, herramienta: Herramienta, llamada: LlamadaHerramienta
    ) -> None:
        confirmacion = ConfirmacionPendiente.nueva(
            mision.id,
            herramienta.nombre,
            llamada.argumentos,
            herramienta.riesgo,
            f"El agente pidió «{herramienta.nombre}» durante la misión.",
            self._reloj.ahora(),
            llamada.id,
        )
        self._confirmaciones.guardar(confirmacion)
        self._registrar(
            mision.id,
            TipoPaso.CONFIRMACION,
            herramienta=herramienta.nombre,
            entrada=llamada.argumentos,
            salida={"estado": "PENDIENTE"},
            llamada_id=llamada.id,
            confirmacion_id=confirmacion.id,
        )
        mision.esperar_confirmacion()


@dataclass(frozen=True)
class Resolucion:
    confirmacion: ConfirmacionPendiente
    continuar_mision: bool  # true si hay que volver a llamar al LLM (misión con LLM en curso)


class _Resolver(_Base):
    def __init__(
        self,
        misiones: MisionRepository,
        confirmaciones: ConfirmacionRepository,
        bitacora: BitacoraRepository,
        reloj: Reloj,
        catalogo: CatalogoHerramientas,
    ) -> None:
        super().__init__(misiones, confirmaciones, bitacora, reloj)
        self._catalogo = catalogo

    def _cargar(self, confirmacion_id: UUID) -> tuple[ConfirmacionPendiente, Mision]:
        confirmacion = self._confirmaciones.obtener(confirmacion_id)
        if confirmacion is None:
            raise ConfirmacionNoEncontrada(str(confirmacion_id))
        return confirmacion, self._mision(confirmacion.mision_id)

    def _cerrar(
        self, confirmacion: ConfirmacionPendiente, mision: Mision, texto_final: str, admin_sub: str
    ) -> bool:
        """Devuelve la misión al estado que corresponde tras resolver; `true` si el LLM debe continuar."""
        if mision.estado is EstadoMision.ESPERANDO_CONFIRMACION:
            mision.reanudar()
        if not mision.con_llm and mision.estado is EstadoMision.EN_CURSO:  # solicitud llegada por MCP
            mision.completar(texto_final, self._reloj.ahora())
        self._misiones.guardar(mision)
        return mision.con_llm and mision.estado is EstadoMision.EN_CURSO


class ConfirmarAccion(_Resolver):
    def aprobar(self, confirmacion_id: UUID, admin_sub: str) -> Resolucion:
        confirmacion, mision = self._cargar(confirmacion_id)
        confirmacion.aprobar(admin_sub, self._reloj.ahora())
        self._confirmaciones.guardar(
            confirmacion
        )  # si otro ADMIN llegó antes: ConflictoDeVersion, no se ejecuta
        try:
            confirmacion.registrar_ejecucion(
                self._catalogo.ejecutar(confirmacion.herramienta, confirmacion.argumentos)
            )
        except Exception as e:
            confirmacion.registrar_fallo(str(e))
        self._confirmaciones.guardar(confirmacion)
        self._registrar(
            mision.id,
            TipoPaso.RESULTADO_HERRAMIENTA,
            herramienta=confirmacion.herramienta,
            salida=confirmacion.resultado or {},
            llamada_id=confirmacion.llamada_id,
            confirmacion_id=confirmacion.id,
            confirmado_por=admin_sub,
        )
        continuar = self._cerrar(
            confirmacion,
            mision,
            f"Acción «{confirmacion.herramienta}» {confirmacion.estado.lower()}.",
            admin_sub,
        )
        return Resolucion(confirmacion, continuar)


class RechazarAccion(_Resolver):
    def rechazar(self, confirmacion_id: UUID, admin_sub: str) -> Resolucion:
        confirmacion, mision = self._cargar(confirmacion_id)
        confirmacion.rechazar(admin_sub, self._reloj.ahora())
        self._confirmaciones.guardar(confirmacion)
        self._registrar(
            mision.id,
            TipoPaso.RESULTADO_HERRAMIENTA,
            herramienta=confirmacion.herramienta,
            salida={"rechazada": True, "motivo": "El ADMIN rechazó la acción: no se ejecutó."},
            llamada_id=confirmacion.llamada_id,
            confirmacion_id=confirmacion.id,
            confirmado_por=admin_sub,
        )
        if not mision.con_llm and mision.estado is EstadoMision.ESPERANDO_CONFIRMACION:
            mision.reanudar()
            mision.cancelar("El ADMIN rechazó la acción solicitada.", self._reloj.ahora())
            self._misiones.guardar(mision)
            return Resolucion(confirmacion, False)
        return Resolucion(confirmacion, self._cerrar(confirmacion, mision, "", admin_sub))


@dataclass(frozen=True)
class VistaMision:
    mision: Mision
    pasos: list[PasoBitacora]
    confirmaciones: list[ConfirmacionPendiente]


class ConsultarMision(_Base):
    def ver(self, mision_id: UUID) -> VistaMision:
        mision = self._mision(mision_id)
        return VistaMision(
            mision, self._bitacora.listar(mision_id), self._confirmaciones.de_mision(mision_id)
        )


class SolicitarAccion(_Base):
    """Una herramienta de escritura pedida por un cliente MCP externo: igual que con el agente, queda
    pendiente (G2)."""

    def __init__(
        self,
        misiones: MisionRepository,
        confirmaciones: ConfirmacionRepository,
        bitacora: BitacoraRepository,
        reloj: Reloj,
        catalogo: CatalogoHerramientas,
    ) -> None:
        super().__init__(misiones, confirmaciones, bitacora, reloj)
        self._catalogo = catalogo

    def solicitar(self, nombre: str, argumentos: dict[str, Any]) -> ConfirmacionPendiente:
        herramienta = self._catalogo.obtener(nombre)
        if herramienta is None or herramienta.riesgo is Riesgo.LECTURA:
            raise ArgumentosInvalidos(f"«{nombre}» no es una herramienta que requiera confirmación")
        try:
            self._catalogo.validar(nombre, argumentos)
        except ValueError as e:
            raise ArgumentosInvalidos(str(e)) from e
        mision = Mision.nueva(
            TipoMision.LIBRE,
            f"Solicitud recibida por MCP: {nombre}",
            "mcp",
            self._reloj.ahora(),
            con_llm=False,
        )
        confirmacion = ConfirmacionPendiente.nueva(
            mision.id,
            nombre,
            argumentos,
            herramienta.riesgo,
            "Solicitada por un cliente MCP.",
            self._reloj.ahora(),
            llamada_id=f"mcp-{mision.id}",
        )
        self._misiones.guardar(mision)
        self._confirmaciones.guardar(confirmacion)
        self._registrar(
            mision.id,
            TipoPaso.CONFIRMACION,
            herramienta=nombre,
            entrada=argumentos,
            salida={"estado": "PENDIENTE"},
            llamada_id=confirmacion.llamada_id,
            confirmacion_id=confirmacion.id,
        )
        mision.esperar_confirmacion()
        self._misiones.guardar(mision)
        return confirmacion
