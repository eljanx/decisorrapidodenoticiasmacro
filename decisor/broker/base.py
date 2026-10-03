from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..riesgo import PlanOrden


@dataclass
class InfoContrato:
    precio: float
    tick: float = 0.01
    multiplicador: float = 1.0


@dataclass
class ResultadoOrden:
    ok: bool
    referencia: str
    detalle: str


class Broker(ABC):
    nombre = "broker"

    async def conectar(self) -> None:  # noqa: B027
        pass

    async def cerrar(self) -> None:  # noqa: B027
        pass

    @abstractmethod
    async def info(self, simbolo: str, tipo: str) -> InfoContrato: ...

    @abstractmethod
    async def variacion_desde(self, simbolos: list[str], desde: datetime) -> dict[str, float]:
        """% de variación de cada símbolo desde `desde` hasta ahora (los que no se puedan, se omiten)."""

    @abstractmethod
    async def enviar(self, plan: PlanOrden) -> ResultadoOrden: ...

    @abstractmethod
    async def cerrar_posicion(self, referencia: str) -> ResultadoOrden: ...

    @abstractmethod
    async def posiciones(self) -> list[str]: ...
