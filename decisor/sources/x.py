"""X (Twitter) mediante la API v2 oficial.

Leer publicaciones requiere un plan de pago (el nivel gratuito no sirve para
monitorizar). Con un token sin permisos, la fuente se desactiva sola.
"""

from __future__ import annotations

from datetime import datetime

from ..modelos import Publicacion
from .base import Fuente, FuenteNoDisponible, Limitada

BASE = "https://api.x.com/2"


class X(Fuente):
    _id_usuario: str | None = None
    _ultimo_id: str | None = None

    def __init__(self, cfg, http, token: str):
        super().__init__(cfg, http)
        if not token:
            raise FuenteNoDisponible("X necesita X_BEARER_TOKEN (API de pago). Usa un puente RSS como alternativa.")
        self._cab = {"Authorization": f"Bearer {token}"}

    async def _get(self, ruta: str, params: dict | None = None) -> dict:
        r = await self.http.get(f"{BASE}{ruta}", params=params, headers=self._cab)
        if r.status_code == 429:
            reset = float(r.headers.get("x-rate-limit-reset", 0))
            espera = max(reset - datetime.now().timestamp(), 60) if reset else 900
            raise Limitada(espera)
        if r.status_code in (401, 403):
            raise FuenteNoDisponible(f"X rechazó la petición ({r.status_code}): el plan de API no permite lectura")
        r.raise_for_status()
        return r.json()

    async def leer(self) -> list[Publicacion]:
        if self._id_usuario is None:
            datos = await self._get(f"/users/by/username/{self.cfg.cuenta}")
            self._id_usuario = datos["data"]["id"]
        params = {"max_results": "5", "tweet.fields": "created_at", "exclude": "replies"}
        if self._ultimo_id:
            params["since_id"] = self._ultimo_id
        datos = await self._get(f"/users/{self._id_usuario}/tweets", params)
        tweets = datos.get("data", [])
        if tweets:
            self._ultimo_id = max((t["id"] for t in tweets), key=int)
        return [
            Publicacion(
                fuente=self.clave,
                autor=self.cfg.nombre,
                id_externo=t["id"],
                texto=t["text"],
                url=f"https://x.com/{self.cfg.cuenta}/status/{t['id']}",
                publicado=datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")),
            )
            for t in tweets
        ]
