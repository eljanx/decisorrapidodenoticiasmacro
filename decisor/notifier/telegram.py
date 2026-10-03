"""Bot de Telegram mediante la Bot API (HTTP). Solo obedece al chat configurado."""

from __future__ import annotations

import asyncio
import logging

import httpx2 as httpx

from .base import Manejador, Notificador, Teclado

log = logging.getLogger(__name__)


def _teclado(teclado: Teclado | None) -> dict | None:
    if not teclado:
        return None
    return {"inline_keyboard": [[{"text": b.texto, "callback_data": b.datos} for b in fila] for fila in teclado]}


class Telegram(Notificador):
    def __init__(self, token: str, chat_id: str, http: httpx.AsyncClient):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.http = http
        self._offset = 0

    async def _llamar(self, metodo: str, timeout: float = 15, **datos) -> dict:
        datos = {k: v for k, v in datos.items() if v is not None}
        r = await self.http.post(f"{self.base}/{metodo}", json=datos, timeout=timeout)
        cuerpo = r.json()
        if not cuerpo.get("ok"):
            raise RuntimeError(f"Telegram {metodo}: {cuerpo.get('description')}")
        return cuerpo["result"]

    async def enviar(self, texto: str, teclado: Teclado | None = None) -> str:
        res = await self._llamar(
            "sendMessage", chat_id=self.chat_id, text=texto[:4096], parse_mode="HTML",
            disable_web_page_preview=True, reply_markup=_teclado(teclado),
        )
        return str(res["message_id"])

    async def editar(self, id_mensaje: str, texto: str, teclado: Teclado | None = None) -> None:
        try:
            await self._llamar(
                "editMessageText", chat_id=self.chat_id, message_id=int(id_mensaje), text=texto[:4096],
                parse_mode="HTML", disable_web_page_preview=True, reply_markup=_teclado(teclado),
            )
        except RuntimeError as e:
            if "not modified" not in str(e):
                raise

    async def escuchar(self, manejador: Manejador) -> None:
        while True:
            try:
                updates = await self._get_updates()
            except Exception as e:
                log.warning("Error leyendo Telegram: %s", e)
                await asyncio.sleep(3)
                continue
            for u in updates:
                self._offset = u["update_id"] + 1
                await self._procesar(u, manejador)

    async def _get_updates(self) -> list[dict]:
        r = await self.http.post(
            f"{self.base}/getUpdates",
            json={"offset": self._offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
            timeout=40,
        )
        cuerpo = r.json()
        if not cuerpo.get("ok"):
            raise RuntimeError(cuerpo.get("description"))
        return cuerpo["result"]

    async def _procesar(self, u: dict, manejador: Manejador) -> None:
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = str(cq.get("message", {}).get("chat", {}).get("id"))
            await self._llamar("answerCallbackQuery", callback_query_id=cq["id"])
            if chat != self.chat_id:
                log.warning("Botón ignorado de chat no autorizado %s", chat)
                return
            await self._seguro(manejador, "boton", cq.get("data", ""))
            return
        msg = u.get("message") or {}
        chat = str(msg.get("chat", {}).get("id"))
        texto = (msg.get("text") or "").strip()
        if chat != self.chat_id:
            if texto.startswith("/start"):
                # Permite descubrir el chat_id la primera vez, sin dar acceso.
                await self._llamar("sendMessage", chat_id=chat,
                                   text=f"Tu chat_id es {chat}. Ponlo en TELEGRAM_CHAT_ID y reinicia el decisor.")
            else:
                log.warning("Mensaje ignorado de chat no autorizado %s", chat)
            return
        if texto:
            await self._seguro(manejador, "comando" if texto.startswith("/") else "texto", texto)

    async def _seguro(self, manejador: Manejador, tipo: str, contenido: str) -> None:
        try:
            await manejador(tipo, contenido)
        except Exception as e:
            log.exception("Error procesando %s %r", tipo, contenido)
            await self.enviar(f"⚠️ Error: {e}")
