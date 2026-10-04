"""Fuente RSS/Atom genérica: archivos de Truth Social, Fed, BCE, Casa Blanca,
o un puente RSS de X (RSSHub autoalojado)."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone

import feedparser
from curl_cffi.requests import AsyncSession

from ..modelos import Publicacion
from .base import Fuente, FuenteNoDisponible, Limitada, html_a_texto


class RSS(Fuente):
    """Usa huella de navegador (curl_cffi): webs como whitehouse.gov rechazan clientes que no lo parecen."""

    _etag: str | None = None
    _modificado: str | None = None
    _sesion: AsyncSession | None = None

    async def leer(self) -> list[Publicacion]:
        if self._sesion is None:
            self._sesion = AsyncSession(impersonate="chrome", timeout=20)
        cab = {}
        if self._etag:
            cab["If-None-Match"] = self._etag
        if self._modificado:
            cab["If-Modified-Since"] = self._modificado
        r = await self._sesion.get(self.cfg.url, headers=cab, allow_redirects=True)
        if r.status_code == 304:
            return []
        if r.status_code in (404, 410):
            raise FuenteNoDisponible(f"la dirección {self.cfg.url} no existe (error {r.status_code})")
        if r.status_code == 429:
            raise Limitada(max(float(r.headers.get("retry-after") or 0), 120))
        r.raise_for_status()
        self._etag = r.headers.get("etag")
        self._modificado = r.headers.get("last-modified")
        return parsear(r.content, self.clave, self.cfg.nombre)


def parsear(contenido: bytes, clave_fuente: str, autor: str) -> list[Publicacion]:
    feed = feedparser.parse(contenido)
    salida = []
    for e in feed.entries[:30]:
        titulo = html_a_texto(e.get("title", ""))
        resumen = html_a_texto(e.get("summary", ""))
        # Muchos feeds de posts repiten el texto en título y resumen.
        texto = resumen if titulo and resumen.startswith(titulo[:40]) else f"{titulo}\n{resumen}".strip()
        fecha = e.get("published_parsed") or e.get("updated_parsed")
        publicado = (
            datetime.fromtimestamp(calendar.timegm(fecha), tz=timezone.utc) if fecha else datetime.now(timezone.utc)
        )
        salida.append(
            Publicacion(
                fuente=clave_fuente,
                autor=autor,
                id_externo=e.get("id") or e.get("link") or titulo[:80],
                texto=texto,
                url=e.get("link", ""),
                publicado=publicado,
            )
        )
    return salida
