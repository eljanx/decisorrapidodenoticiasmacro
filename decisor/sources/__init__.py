from __future__ import annotations

import httpx2 as httpx

from ..config import FuenteCfg
from .base import Fuente, FuenteNoDisponible, Limitada
from .rss import RSS
from .truthsocial import TruthSocial
from .x import X


def crear(cfg: FuenteCfg, http: httpx.AsyncClient, x_token: str = "") -> Fuente:
    if cfg.tipo == "truthsocial":
        return TruthSocial(cfg, http)
    if cfg.tipo == "rss":
        return RSS(cfg, http)
    if cfg.tipo == "x":
        return X(cfg, http, x_token)
    raise ValueError(f"Tipo de fuente desconocido: {cfg.tipo}")


__all__ = ["Fuente", "FuenteNoDisponible", "Limitada", "crear"]
