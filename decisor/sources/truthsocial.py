"""Truth Social mediante su API pública (compatible con Mastodon).

No es una API oficial ni documentada: puede cambiar o quedar bloqueada por
Cloudflare. Por eso conviene tener también una fuente RSS de respaldo.
"""

from __future__ import annotations

from datetime import datetime

from curl_cffi.requests import AsyncSession

from ..modelos import Publicacion
from .base import Fuente, FuenteNoDisponible, Limitada, html_a_texto

BASE = "https://truthsocial.com/api/v1"
MAX_BLOQUEOS = 3


class TruthSocial(Fuente):
    """Usa curl_cffi para presentarse como un navegador Chrome: Cloudflare bloquea
    las peticiones que no lo parecen (error 403)."""

    _id_cuenta: str | None = None
    _ultimo_id: str | None = None
    _sesion: AsyncSession | None = None
    _bloqueos = 0

    async def _get(self, ruta: str, params: dict):
        if self._sesion is None:
            self._sesion = AsyncSession(impersonate="chrome", timeout=15)
        r = await self._sesion.get(f"{BASE}{ruta}", params=params)
        if r.status_code == 403:
            self._bloqueos += 1
            if self._bloqueos >= MAX_BLOQUEOS:
                raise FuenteNoDisponible(
                    "Truth Social bloquea el acceso directo desde tu conexión. "
                    "No pasa nada: sigo recibiendo sus publicaciones por el RSS de respaldo (algo más lento)."
                )
            raise RuntimeError("403 de Truth Social (bloqueo de Cloudflare)")
        self._bloqueos = 0
        if r.status_code == 429:
            raise Limitada(float(r.headers.get("retry-after", 30)))
        r.raise_for_status()
        return r

    async def _resolver_cuenta(self) -> str:
        r = await self._get("/accounts/lookup", {"acct": self.cfg.cuenta})
        if r.status_code == 404:
            raise FuenteNoDisponible(f"Cuenta de Truth Social no encontrada: {self.cfg.cuenta}")
        return str(r.json()["id"])

    async def leer(self) -> list[Publicacion]:
        if self._id_cuenta is None:
            self._id_cuenta = await self._resolver_cuenta()
        params = {"exclude_replies": "true", "limit": "20"}
        if self._ultimo_id:
            params["since_id"] = self._ultimo_id
        r = await self._get(f"/accounts/{self._id_cuenta}/statuses", params)
        estados = r.json()
        if estados:
            self._ultimo_id = max((str(e["id"]) for e in estados), key=int)
        return [self._a_publicacion(e) for e in estados]

    def _a_publicacion(self, e: dict) -> Publicacion:
        texto = html_a_texto(e.get("content", ""))
        if e.get("reblog"):
            original = e["reblog"]
            autor_orig = original.get("account", {}).get("acct", "?")
            texto = f"[ReTruth de @{autor_orig}] " + html_a_texto(original.get("content", ""))
        if not texto:
            tarjeta = e.get("card") or {}
            if tarjeta.get("title"):
                texto = f"[Enlace] {tarjeta['title']} {tarjeta.get('url', '')}".strip()
            elif e.get("media_attachments"):
                texto = "[Publicación solo con imagen o vídeo, sin texto]"
        return Publicacion(
            fuente=self.clave,
            autor=self.cfg.nombre,
            id_externo=str(e["id"]),
            texto=texto,
            url=e.get("url") or "",
            publicado=datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")),
        )
