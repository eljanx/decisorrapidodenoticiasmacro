"""Carga de configuración: config.yaml + variables de entorno (.env)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class FuenteCfg(BaseModel):
    tipo: Literal["truthsocial", "rss", "x"]
    nombre: str
    cuenta: str | None = None
    url: str | None = None
    intervalo_s: float = 15
    activa: bool = True

    @model_validator(mode="after")
    def _check(self) -> "FuenteCfg":
        if self.tipo == "rss" and not self.url:
            raise ValueError(f"La fuente RSS '{self.nombre}' necesita url")
        if self.tipo in ("truthsocial", "x") and not self.cuenta:
            raise ValueError(f"La fuente {self.tipo} '{self.nombre}' necesita cuenta")
        return self

    @property
    def clave(self) -> str:
        return f"{self.tipo}:{self.cuenta or self.url}"


class IACfg(BaseModel):
    modelo_triaje: str = "claude-opus-5-5"
    esfuerzo_triaje: str = "low"
    modelo_analisis: str = "claude-opus-5-5"
    esfuerzo_analisis: str = "medium"
    busqueda_web: bool = True
    umbral_relevancia: int = 50


class MercadoCfg(BaseModel):
    referencia: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "TLT", "GLD", "USO", "UUP"])


class RiesgoCfg(BaseModel):
    importes_rapidos: list[float] = Field(default_factory=lambda: [500, 1000, 2000])
    max_por_operacion: float = 2000
    max_diario: float = 5000
    max_posiciones_abiertas: int = 3
    instrumentos_permitidos: list[str] = Field(default_factory=lambda: ["accion", "etf", "futuro", "divisa"])
    permitir_cortos: bool = False
    stop_min_pct: float = 0.3
    stop_max_pct: float = 5.0
    conviccion_minima: int = 40
    caducidad_min: float = 10
    max_deslizamiento_pct: float = 0.5
    margen_limite_pct: float = 0.15
    simbolos_prohibidos: list[str] = Field(default_factory=list)


class IBKRCfg(BaseModel):
    host: str = "127.0.0.1"
    puerto: int = 4002
    client_id: int = 17
    cuenta: str = ""


class Config(BaseModel):
    modo: Literal["simulado", "paper", "real"] = "simulado"
    confirmo_dinero_real: bool = False
    base_datos: str = "decisor.db"
    fuentes: list[FuenteCfg] = Field(default_factory=list)
    ia: IACfg = Field(default_factory=IACfg)
    mercado: MercadoCfg = Field(default_factory=MercadoCfg)
    riesgo: RiesgoCfg = Field(default_factory=RiesgoCfg)
    ibkr: IBKRCfg = Field(default_factory=IBKRCfg)

    # Secretos (desde el entorno, nunca desde el YAML)
    telegram_token: str = ""
    telegram_chat_id: str = ""
    x_bearer_token: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Config":
        if self.modo == "real" and not self.confirmo_dinero_real:
            raise ValueError("modo: real exige confirmo_dinero_real: true en config.yaml")
        return self


def _cargar_env(ruta: Path) -> None:
    """Lector mínimo de .env (KEY=VALUE). No sobrescribe variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cargar(ruta_config: str = "config.yaml", ruta_env: str = ".env") -> Config:
    _cargar_env(Path(ruta_env))
    datos = {}
    p = Path(ruta_config)
    if p.exists():
        datos = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    datos["telegram_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    datos["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID", "")
    datos["x_bearer_token"] = os.environ.get("X_BEARER_TOKEN", "")
    return Config.model_validate(datos)
