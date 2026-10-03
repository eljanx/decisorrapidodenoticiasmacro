"""Arranque: python -m decisor [--config config.yaml] [--consola]"""

from __future__ import annotations

import argparse
import asyncio
import logging

import httpx2 as httpx

from . import broker as brokers
from .almacen import Almacen
from .app import Decisor
from .config import cargar
from .ia import IA
from .notifier import Consola, Telegram


async def principal(args) -> None:
    cfg = cargar(args.config, args.env)
    async with httpx.AsyncClient(timeout=15, http2=False) as http:
        if args.consola or not (cfg.telegram_token and cfg.telegram_chat_id):
            if not args.consola:
                logging.warning("Sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID: uso la consola")
            notif = Consola()
        else:
            notif = Telegram(cfg.telegram_token, cfg.telegram_chat_id, http)
        decisor = Decisor(cfg, Almacen(cfg.base_datos), IA(cfg.ia), brokers.crear(cfg), notif, http)
        await decisor.ejecutar_siempre()


def main() -> None:
    p = argparse.ArgumentParser(description="Decisor rápido de noticias macro")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--env", default=".env")
    p.add_argument("--consola", action="store_true", help="usar la consola en lugar de Telegram")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    try:
        asyncio.run(principal(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
