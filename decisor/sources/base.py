"""Interfaz común de las fuentes. Cada fuente se consulta periódicamente (polling)."""

from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod

import httpx2 as httpx

from ..config import FuenteCfg
from ..modelos import Publicacion

CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, application/rss+xml, application/xml, text/xml, */*",
}


class FuenteNoDisponible(Exception):
    """Error permanente (credenciales, plan de API insuficiente): se desactiva la fuente."""


class Limitada(Exception):
    """La fuente ha devuelto 429: esperar `espera_s` antes de reintentar."""

    def __init__(self, espera_s: float):
        super().__init__(f"rate limit, esperar {espera_s:.0f}s")
        self.espera_s = espera_s


def html_a_texto(contenido: str) -> str:
    t = re.sub(r"<br\s*/?>|</p>\s*<p>", "\n", contenido or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t).strip()


class Fuente(ABC):
    def __init__(self, cfg: FuenteCfg, http: httpx.AsyncClient):
        self.cfg = cfg
        self.http = http

    @property
    def clave(self) -> str:
        return self.cfg.clave

    @abstractmethod
    async def leer(self) -> list[Publicacion]:
        """Devuelve las publicaciones recientes (las ya vistas se filtran fuera)."""
