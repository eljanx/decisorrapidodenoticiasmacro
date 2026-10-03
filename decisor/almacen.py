"""Persistencia en SQLite: posts vistos, fuentes dinámicas, eventos y órdenes.

Cada evento guarda las marcas de tiempo de cada fase para medir la latencia real
y poder evaluar a posteriori si las propuestas habrían ganado dinero.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

ESQUEMA = """
CREATE TABLE IF NOT EXISTS vistos (
    clave TEXT PRIMARY KEY,
    huella TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS vistos_huella ON vistos(huella);

CREATE TABLE IF NOT EXISTS fuentes_extra (
    clave TEXT PRIMARY KEY,
    datos TEXT NOT NULL,
    activa INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave_post TEXT NOT NULL,
    fuente TEXT NOT NULL,
    autor TEXT NOT NULL,
    texto TEXT NOT NULL,
    url TEXT,
    publicado TEXT,
    detectado TEXT,
    triaje TEXT,
    triaje_ts TEXT,
    aviso_ts TEXT,
    analisis TEXT,
    analisis_ts TEXT,
    precio_ref REAL,
    estado TEXT NOT NULL DEFAULT 'nuevo',
    decision_importe REAL,
    decision_ts TEXT,
    orden TEXT,
    nota TEXT
);

CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


class Almacen:
    def __init__(self, ruta: str):
        self.db = sqlite3.connect(ruta, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(ESQUEMA)
        self.db.commit()

    # --- deduplicación -------------------------------------------------------
    def ya_visto(self, clave: str, huella: str, ventana_h: float = 6) -> bool:
        desde = (datetime.now(timezone.utc) - timedelta(hours=ventana_h)).isoformat()
        fila = self.db.execute(
            "SELECT 1 FROM vistos WHERE clave = ? OR (huella = ? AND ts >= ?) LIMIT 1",
            (clave, huella, desde),
        ).fetchone()
        return fila is not None

    def marcar_visto(self, clave: str, huella: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO vistos (clave, huella, ts) VALUES (?, ?, ?)",
            (clave, huella, _ahora()),
        )
        self.db.commit()

    # --- fuentes añadidas desde Telegram -------------------------------------
    def fuentes_extra(self) -> list[dict]:
        filas = self.db.execute("SELECT datos FROM fuentes_extra WHERE activa = 1").fetchall()
        return [json.loads(f["datos"]) for f in filas]

    def guardar_fuente(self, clave: str, datos: dict) -> None:
        self.db.execute(
            "INSERT INTO fuentes_extra (clave, datos, activa) VALUES (?, ?, 1) "
            "ON CONFLICT(clave) DO UPDATE SET datos = excluded.datos, activa = 1",
            (clave, json.dumps(datos)),
        )
        self.db.commit()

    def desactivar_fuente(self, clave: str) -> bool:
        cur = self.db.execute("UPDATE fuentes_extra SET activa = 0 WHERE clave = ?", (clave,))
        self.db.commit()
        return cur.rowcount > 0

    # --- ajustes en caliente (pausa, fuentes de config desactivadas) ---------
    def ajuste(self, clave: str, defecto: Any = None) -> Any:
        fila = self.db.execute("SELECT valor FROM ajustes WHERE clave = ?", (clave,)).fetchone()
        return json.loads(fila["valor"]) if fila else defecto

    def fijar_ajuste(self, clave: str, valor: Any) -> None:
        self.db.execute(
            "INSERT INTO ajustes (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, json.dumps(valor)),
        )
        self.db.commit()

    # --- eventos -------------------------------------------------------------
    def crear_evento(self, post) -> int:
        cur = self.db.execute(
            "INSERT INTO eventos (clave_post, fuente, autor, texto, url, publicado, detectado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                post.clave,
                post.fuente,
                post.autor,
                post.texto,
                post.url,
                post.publicado.isoformat(),
                post.detectado.isoformat(),
            ),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def actualizar(self, id_evento: int, **campos: Any) -> None:
        if not campos:
            return
        for k, v in list(campos.items()):
            if hasattr(v, "model_dump_json"):
                campos[k] = v.model_dump_json()
            elif isinstance(v, (dict, list)):
                campos[k] = json.dumps(v)
        sets = ", ".join(f"{k} = ?" for k in campos)
        self.db.execute(f"UPDATE eventos SET {sets} WHERE id = ?", (*campos.values(), id_evento))
        self.db.commit()

    def evento(self, id_evento: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM eventos WHERE id = ?", (id_evento,)).fetchone()

    def recientes_de(self, autor: str, n: int = 8, excluir: int | None = None) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT publicado, texto FROM eventos WHERE autor = ? AND id != ? "
            "ORDER BY id DESC LIMIT ?",
            (autor, excluir or -1, n),
        ).fetchall()

    def importe_ejecutado_hoy(self) -> float:
        hoy = datetime.now(timezone.utc).date().isoformat()
        fila = self.db.execute(
            "SELECT COALESCE(SUM(decision_importe), 0) AS s FROM eventos "
            "WHERE estado IN ('ejecutado', 'cerrado') AND substr(decision_ts, 1, 10) = ?",
            (hoy,),
        ).fetchone()
        return float(fila["s"])

    def abiertos(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM eventos WHERE estado = 'ejecutado'").fetchall()

    def ultimos(self, n: int = 10) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM eventos ORDER BY id DESC LIMIT ?", (n,)).fetchall()
