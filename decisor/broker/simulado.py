"""Bróker simulado: no envía nada, solo registra. Útil para probar el flujo sin IBKR."""

from __future__ import annotations

import itertools
import logging
from datetime import datetime

from ..riesgo import PlanOrden
from .base import Broker, InfoContrato, ResultadoOrden

log = logging.getLogger(__name__)


class Simulado(Broker):
    nombre = "simulado"

    def __init__(self, precios: dict[str, float] | None = None):
        self.precios = precios or {}
        self._ids = itertools.count(1)
        self._abiertas: dict[str, PlanOrden] = {}

    async def info(self, simbolo: str, tipo: str) -> InfoContrato:
        # Sin datos reales, un precio ficticio permite recorrer el flujo completo.
        return InfoContrato(precio=self.precios.get(simbolo.upper(), 100.0))

    async def variacion_desde(self, simbolos, desde: datetime) -> dict[str, float]:
        return {}

    async def enviar(self, plan: PlanOrden) -> ResultadoOrden:
        ref = f"SIM-{next(self._ids)}"
        self._abiertas[ref] = plan
        log.info("Orden simulada %s: %s", ref, plan)
        return ResultadoOrden(True, ref, f"[SIMULADO] {plan.accion} {plan.cantidad:g} {plan.simbolo}")

    async def cerrar_posicion(self, referencia: str) -> ResultadoOrden:
        plan = self._abiertas.pop(referencia, None)
        if not plan:
            return ResultadoOrden(False, referencia, "No existe esa posición simulada")
        return ResultadoOrden(True, referencia, f"[SIMULADO] cerrada {plan.simbolo}")

    async def posiciones(self) -> list[str]:
        return [f"{r}: {p.accion} {p.cantidad:g} {p.simbolo} @ {p.limite}" for r, p in self._abiertas.items()]
