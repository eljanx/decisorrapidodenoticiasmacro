"""Conexión con Interactive Brokers mediante IB Gateway / TWS y ib_async.

Requisitos: IB Gateway en marcha en la misma máquina, con la API activada
(Configure → Settings → API) y el puerto del config (4002 paper, 4001 real).
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone

from ib_async import IB, ContFuture, Contract, Forex, MarketOrder, Stock

from ..config import IBKRCfg
from ..riesgo import PlanOrden
from .base import Broker, InfoContrato, ResultadoOrden

log = logging.getLogger(__name__)

# Bolsa por defecto de los futuros más habituales (raíz → exchange).
BOLSA_FUTUROS = {
    "ES": "CME", "MES": "CME", "NQ": "CME", "MNQ": "CME", "RTY": "CME", "M2K": "CME",
    "YM": "CBOT", "MYM": "CBOT", "ZN": "CBOT", "ZB": "CBOT", "ZF": "CBOT",
    "CL": "NYMEX", "MCL": "NYMEX", "NG": "NYMEX",
    "GC": "COMEX", "MGC": "COMEX", "SI": "COMEX", "HG": "COMEX",
    "6E": "CME", "6J": "CME", "6B": "CME",
}


class IBKR(Broker):
    nombre = "ibkr"

    def __init__(self, cfg: IBKRCfg):
        self.cfg = cfg
        self.ib = IB()
        self._contratos: dict[tuple[str, str], Contract] = {}

    async def conectar(self) -> None:
        await self.ib.connectAsync(self.cfg.host, self.cfg.puerto, clientId=self.cfg.client_id,
                                   account=self.cfg.cuenta, timeout=10)
        # 3 = datos diferidos si no hay suscripción en tiempo real (gratis, 15 min de retraso).
        self.ib.reqMarketDataType(3)
        log.info("Conectado a IBKR en %s:%s", self.cfg.host, self.cfg.puerto)

    async def cerrar(self) -> None:
        self.ib.disconnect()

    async def _asegurar(self) -> None:
        if not self.ib.isConnected():
            await self.conectar()

    async def _contrato(self, simbolo: str, tipo: str) -> Contract:
        clave = (simbolo.upper(), tipo)
        if clave in self._contratos:
            return self._contratos[clave]
        s = simbolo.upper()
        if tipo == "futuro":
            c = ContFuture(s, exchange=BOLSA_FUTUROS.get(s, "CME"))
        elif tipo == "divisa":
            c = Forex(s)
        else:
            c = Stock(s, "SMART", "USD")
        calificados = await self.ib.qualifyContractsAsync(c)
        if not calificados or calificados[0] is None:
            raise ValueError(f"IBKR no reconoce el contrato {s} ({tipo})")
        c = calificados[0]
        if tipo == "futuro":
            # ContFuture sirve para consultar; para operar hace falta el contrato concreto.
            c = Contract(conId=c.conId, exchange=c.exchange)
            c = (await self.ib.qualifyContractsAsync(c))[0]
        self._contratos[clave] = c
        return c

    async def info(self, simbolo: str, tipo: str) -> InfoContrato:
        await self._asegurar()
        c = await self._contrato(simbolo, tipo)
        [ticker] = await self.ib.reqTickersAsync(c)
        precio = ticker.marketPrice()
        if precio is None or math.isnan(precio):
            precio = ticker.close
        detalles = await self.ib.reqContractDetailsAsync(c)
        tick = detalles[0].minTick if detalles else 0.01
        mult = float(c.multiplier) if getattr(c, "multiplier", "") else 1.0
        return InfoContrato(precio=float(precio or 0), tick=tick or 0.01, multiplicador=mult)

    async def variacion_desde(self, simbolos: list[str], desde: datetime) -> dict[str, float]:
        await self._asegurar()

        async def una(sim: str) -> tuple[str, float] | None:
            try:
                c = await self._contrato(sim, "etf")
                barras = await self.ib.reqHistoricalDataAsync(
                    c, endDateTime="", durationStr="7200 S", barSizeSetting="1 min",
                    whatToShow="TRADES", useRTH=False, formatDate=2, timeout=8,
                )
                if not barras:
                    return None
                desde_utc = desde.astimezone(timezone.utc)
                previas = [b for b in barras if b.date.astimezone(timezone.utc) <= desde_utc]
                base = (previas[-1] if previas else barras[0]).close
                return sim, (barras[-1].close - base) / base * 100
            except Exception as e:  # un símbolo sin datos no debe frenar el resto
                log.debug("Sin variación para %s: %s", sim, e)
                return None

        resultados = await asyncio.gather(*(una(s) for s in simbolos))
        return dict(r for r in resultados if r)

    async def enviar(self, plan: PlanOrden) -> ResultadoOrden:
        await self._asegurar()
        c = await self._contrato(plan.simbolo, plan.tipo_instrumento)
        bracket = self.ib.bracketOrder(plan.accion, plan.cantidad, plan.limite, plan.objetivo, plan.stop)
        bracket.parent.tif = "DAY"
        bracket.parent.outsideRth = plan.tipo_instrumento in ("accion", "etf")
        for o in (bracket.takeProfit, bracket.stopLoss):
            o.tif = "GTC"
            o.outsideRth = plan.tipo_instrumento in ("accion", "etf")
        trades = [self.ib.placeOrder(c, o) for o in bracket]
        await asyncio.sleep(1)
        estado = trades[0].orderStatus.status
        ref = str(bracket.parent.orderId)
        detalle = (
            f"{plan.accion} {plan.cantidad:g} {plan.simbolo} límite {plan.limite} · "
            f"stop {plan.stop} · objetivo {plan.objetivo} · estado: {estado}"
        )
        ok = estado not in ("Cancelled", "ApiCancelled", "Inactive")
        return ResultadoOrden(ok, ref, detalle)

    async def cerrar_posicion(self, referencia: str) -> ResultadoOrden:
        """Cancela las órdenes hijas del bracket y cierra a mercado lo ejecutado."""
        await self._asegurar()
        padre_id = int(referencia)
        trades = [t for t in self.ib.openTrades() if t.order.orderId == padre_id or t.order.parentId == padre_id]
        padre = next((t for t in self.ib.trades() if t.order.orderId == padre_id), None)
        for t in trades:
            self.ib.cancelOrder(t.order)
        if padre is None:
            return ResultadoOrden(False, referencia, "No encuentro la orden original en esta sesión de IBKR")
        ejecutado = padre.orderStatus.filled
        if ejecutado <= 0:
            return ResultadoOrden(True, referencia, "La entrada no llegó a ejecutarse; órdenes canceladas")
        lado = "SELL" if padre.order.action == "BUY" else "BUY"
        self.ib.placeOrder(padre.contract, MarketOrder(lado, ejecutado))
        return ResultadoOrden(True, referencia, f"Cierre a mercado enviado: {lado} {ejecutado:g} {padre.contract.symbol}")

    async def posiciones(self) -> list[str]:
        await self._asegurar()
        return [
            f"{p.contract.symbol} {p.position:g} @ {p.avgCost:.2f}"
            for p in self.ib.positions() if p.position
        ]
