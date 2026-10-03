from __future__ import annotations

from .base import Broker, InfoContrato, ResultadoOrden
from .simulado import Simulado


def crear(cfg) -> Broker:
    if cfg.modo == "simulado":
        return Simulado()
    from .ibkr import IBKR  # importación diferida: ib_async solo hace falta en paper/real

    return IBKR(cfg.ibkr)


__all__ = ["Broker", "InfoContrato", "ResultadoOrden", "crear"]
