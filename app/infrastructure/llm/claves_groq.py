"""Varias claves de Groq en una variable (`GROQ_API_KEY=k1,k2,k3`): si una se agota, se usa la siguiente."""


class ClavesGroq:
    def __init__(self, crudo: str) -> None:
        self._claves = [c.strip() for c in crudo.split(",") if c.strip()]
        self._actual = 0  # la que funcionó por última vez: las llamadas siguientes empiezan por ella

    def __bool__(self) -> bool:
        return bool(self._claves)

    def __len__(self) -> int:
        return len(self._claves)

    def actual(self) -> str:
        return self._claves[self._actual]

    def rotar(self) -> None:
        self._actual = (self._actual + 1) % len(self._claves)


# 429: límite agotado; 401: clave inválida o revocada. Ambos se resuelven con otra clave.
CODIGOS_DE_CLAVE_AGOTADA = frozenset({401, 429})
