"""Estructuras de datos del flujo: publicación → triaje → análisis → propuesta."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class Publicacion(BaseModel):
    fuente: str  # clave de la fuente, p. ej. "truthsocial:realDonaldTrump"
    autor: str
    id_externo: str
    texto: str
    url: str = ""
    publicado: datetime
    detectado: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def clave(self) -> str:
        return f"{self.fuente}:{self.id_externo}"

    @property
    def huella(self) -> str:
        """Hash del texto normalizado: detecta el mismo post llegado por dos fuentes."""
        t = re.sub(r"https?://\S+", "", self.texto.lower())
        t = re.sub(r"[^\w]+", " ", t).strip()
        return hashlib.sha256(f"{self.autor.lower()}|{t[:280]}".encode()).hexdigest()[:24]


class Triaje(BaseModel):
    relevante: bool
    sorpresa_preliminar: int = Field(ge=0, le=100)
    alcance: Literal["macro", "sector", "empresa", "ninguno"]
    titular: str
    motivo: str


class ActivoAfectado(BaseModel):
    simbolo: str
    nombre: str
    direccion: Literal["alcista", "bajista"]
    motivo: str


Instrumento = Literal["accion", "etf", "futuro", "opcion", "divisa"]


class Propuesta(BaseModel):
    operar: bool
    simbolo: str | None
    tipo_instrumento: Instrumento | None
    accion: Literal["comprar", "vender"] | None
    stop_pct: float | None
    objetivo_pct: float | None
    horizonte_min: int | None
    conviccion: int = Field(ge=0, le=100)
    motivo: str


class Analisis(BaseModel):
    sorpresa: int = Field(ge=0, le=100)
    sorpresa_motivo: str
    relevante: bool
    alcance: Literal["macro", "sector", "empresa", "ninguno"]
    activos_afectados: list[ActivoAfectado]
    ya_cotizado: str
    explicacion: str
    propuesta: Propuesta
