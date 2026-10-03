"""Motor de riesgo determinista. Es la única puerta entre la IA y el bróker.

Ninguna orden se construye si no pasa todas estas reglas, diga lo que diga la IA.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import RiesgoCfg
from .modelos import Propuesta


class Rechazo(Exception):
    def __init__(self, motivos: list[str]):
        super().__init__("; ".join(motivos))
        self.motivos = motivos


@dataclass
class PlanOrden:
    simbolo: str
    tipo_instrumento: str
    accion: str  # BUY / SELL
    cantidad: float
    limite: float
    stop: float
    objetivo: float
    horizonte_min: int
    importe: float


def validar_propuesta(p: Propuesta, cfg: RiesgoCfg) -> list[str]:
    """Problemas que impiden ejecutar la propuesta tal cual. Lista vacía = ejecutable."""
    if not p.operar:
        return ["La IA recomienda no operar"]
    motivos = []
    if not p.simbolo or not p.tipo_instrumento or not p.accion:
        motivos.append("Propuesta incompleta (falta símbolo, tipo o dirección)")
        return motivos
    if p.tipo_instrumento not in cfg.instrumentos_permitidos:
        motivos.append(f"Instrumento '{p.tipo_instrumento}' no permitido para ejecución automática")
    if p.simbolo.upper() in {s.upper() for s in cfg.simbolos_prohibidos}:
        motivos.append(f"{p.simbolo} está en la lista de prohibidos")
    if p.accion == "vender" and p.tipo_instrumento in ("accion", "etf") and not cfg.permitir_cortos:
        motivos.append("Venta en corto no permitida (permitir_cortos: false)")
    if p.stop_pct is None or not (cfg.stop_min_pct <= p.stop_pct <= cfg.stop_max_pct):
        motivos.append(f"Stop {p.stop_pct}% fuera del rango {cfg.stop_min_pct}-{cfg.stop_max_pct}%")
    if p.objetivo_pct is None or p.objetivo_pct <= 0:
        motivos.append("Falta objetivo de beneficio")
    if p.conviccion < cfg.conviccion_minima:
        motivos.append(f"Convicción {p.conviccion} por debajo del mínimo {cfg.conviccion_minima}")
    return motivos


def _redondear(precio: float, tick: float) -> float:
    return round(round(precio / tick) * tick, 10)


def planificar(
    p: Propuesta,
    cfg: RiesgoCfg,
    importe: float,
    precio_actual: float,
    precio_ref: float | None,
    propuesta_ts: datetime,
    importe_hoy: float,
    posiciones_abiertas: int,
    pausado: bool,
    tick: float = 0.01,
    multiplicador: float = 1.0,
    ahora: datetime | None = None,
) -> PlanOrden:
    ahora = ahora or datetime.now(timezone.utc)
    motivos = validar_propuesta(p, cfg)
    if pausado:
        motivos.append("Operativa en pausa (/reanudar para activarla)")
    if importe <= 0:
        motivos.append("Importe no válido")
    if importe > cfg.max_por_operacion:
        motivos.append(f"Importe {importe:.0f} supera el máximo por operación ({cfg.max_por_operacion:.0f})")
    if importe_hoy + importe > cfg.max_diario:
        motivos.append(f"Superaría el máximo diario ({importe_hoy:.0f} + {importe:.0f} > {cfg.max_diario:.0f})")
    if posiciones_abiertas >= cfg.max_posiciones_abiertas:
        motivos.append(f"Ya hay {posiciones_abiertas} posiciones abiertas (máximo {cfg.max_posiciones_abiertas})")
    if ahora - propuesta_ts > timedelta(minutes=cfg.caducidad_min):
        motivos.append(f"La propuesta ha caducado (más de {cfg.caducidad_min:.0f} min)")
    if not precio_actual or precio_actual <= 0 or math.isnan(precio_actual):
        motivos.append("Sin precio de mercado para el instrumento")
    compra = p.accion == "comprar"
    if precio_ref and precio_actual and precio_actual > 0:
        movimiento = (precio_actual - precio_ref) / precio_ref * 100
        adverso = movimiento if compra else -movimiento
        if adverso > cfg.max_deslizamiento_pct:
            motivos.append(
                f"El precio se ha movido {movimiento:+.2f}% en contra desde la propuesta "
                f"(máximo {cfg.max_deslizamiento_pct}%). Pide un nuevo análisis."
            )
    if motivos:
        raise Rechazo(motivos)

    signo = 1 if compra else -1
    limite = _redondear(precio_actual * (1 + signo * cfg.margen_limite_pct / 100), tick)
    stop = _redondear(limite * (1 - signo * p.stop_pct / 100), tick)
    objetivo = _redondear(limite * (1 + signo * p.objetivo_pct / 100), tick)

    if p.tipo_instrumento == "futuro":
        cantidad = math.floor(importe / (limite * multiplicador))
        if cantidad < 1:
            raise Rechazo([f"El importe no alcanza para 1 contrato (nocional {limite * multiplicador:,.0f})"])
    elif p.tipo_instrumento == "divisa":
        # Par BASE/COTIZADA: si la cotizada es USD, el importe en USD se convierte a la base.
        cantidad = round(importe / limite) if p.simbolo.upper().endswith("USD") else round(importe)
    else:
        cantidad = math.floor(importe / limite)
        if cantidad < 1:
            raise Rechazo([f"El importe no alcanza para 1 título a {limite}"])

    return PlanOrden(
        simbolo=p.simbolo.upper(),
        tipo_instrumento=p.tipo_instrumento,
        accion="BUY" if compra else "SELL",
        cantidad=cantidad,
        limite=limite,
        stop=stop,
        objetivo=objetivo,
        horizonte_min=p.horizonte_min or 60,
        importe=importe,
    )
