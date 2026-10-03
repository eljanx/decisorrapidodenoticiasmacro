"""Notificador por consola, para probar sin Telegram. Los botones se pulsan escribiendo su código."""

from __future__ import annotations

import asyncio
import itertools
import re
import sys

from .base import Manejador, Notificador, Teclado


class Consola(Notificador):
    def __init__(self):
        self._ids = itertools.count(1)

    async def enviar(self, texto: str, teclado: Teclado | None = None) -> str:
        i = str(next(self._ids))
        print(f"\n===== [{i}] =====\n{re.sub(r'<[^>]+>', '', texto)}")
        if teclado:
            print("Opciones (escribe el código): " + " | ".join(f"{b.texto} → {b.datos}" for fila in teclado for b in fila))
        return i

    async def editar(self, id_mensaje: str, texto: str, teclado: Teclado | None = None) -> None:
        await self.enviar(f"(actualiza {id_mensaje})\n{texto}", teclado)

    async def escuchar(self, manejador: Manejador) -> None:
        """Lee de la entrada estándar: comandos (/probar ...), códigos de botón (e:1:500) o texto."""
        while True:
            linea = await asyncio.to_thread(sys.stdin.readline)
            if not linea:
                await asyncio.Event().wait()  # sin stdin (servicio): seguir vivo sin leer
            linea = linea.strip()
            if not linea:
                continue
            if linea.startswith("/"):
                tipo = "comando"
            elif re.fullmatch(r"[eoncm]:\d+(:[\d.]+)?", linea):
                tipo = "boton"
            else:
                tipo = "texto"
            try:
                await manejador(tipo, linea)
            except Exception as e:  # noqa: BLE001
                print(f"Error: {e}")
