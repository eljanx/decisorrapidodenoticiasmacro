from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class Boton:
    texto: str
    datos: str  # máx. 64 bytes en Telegram


# Filas de botones
Teclado = list[list[Boton]]
Manejador = Callable[[str, str], Awaitable[None]]  # (tipo, contenido)


class Notificador(ABC):
    @abstractmethod
    async def enviar(self, texto: str, teclado: Teclado | None = None) -> str: ...

    @abstractmethod
    async def editar(self, id_mensaje: str, texto: str, teclado: Teclado | None = None) -> None: ...

    async def escuchar(self, manejador: Manejador) -> None:
        """Bucle de entrada del usuario. manejador(tipo, contenido) con tipo en
        {'comando', 'boton', 'texto'}."""
        return None
