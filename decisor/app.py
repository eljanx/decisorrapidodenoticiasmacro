"""Orquestación: fuentes → triaje → aviso → análisis → propuesta → confirmación → orden."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from html import escape

import httpx2 as httpx

from . import sources
from .almacen import Almacen
from .broker import Broker
from .config import Config, FuenteCfg
from .ia import IA, ErrorIA
from .modelos import Analisis, Publicacion, Triaje
from .notifier import Boton, Notificador
from .riesgo import Rechazo, planificar, validar_propuesta

log = logging.getLogger(__name__)

AYUDA = """<b>Decisor rápido de noticias macro</b>

/fuentes – cuentas y fuentes vigiladas
/seguir truth &lt;cuenta&gt; [nombre] – seguir una cuenta de Truth Social
/seguir x &lt;cuenta&gt; [nombre] – seguir una cuenta de X (requiere API de pago)
/seguir rss &lt;url&gt; [nombre] [cada N] – seguir un feed RSS (cada N minutos)
/dejar &lt;clave&gt; – dejar de seguir (la clave sale en /fuentes)
/pausa – no ejecutar operaciones (los avisos siguen)
/reanudar – volver a permitir operaciones
/estado – modo, límites y uso de hoy
/posiciones – posiciones abiertas en el bróker
/ultimas – últimos eventos analizados
/probar &lt;texto&gt; – simula una publicación para probar el flujo"""


def _hace(desde: datetime) -> str:
    s = (datetime.now(timezone.utc) - desde).total_seconds()
    return f"{s:.0f} s" if s < 120 else f"{s / 60:.0f} min"


def _barra(valor: int) -> str:
    llenos = round(valor / 10)
    return "▰" * llenos + "▱" * (10 - llenos) + f" {valor}"


def leer_importe(texto: str) -> float:
    """Acepta '1500', '1.500', '1,500', '1500,5', '1500.5', '$1.000'."""
    t = texto.replace("$", "").replace("€", "").replace(" ", "").strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t or "." in t:
        sep = "," if "," in t else "."
        entero, _, dec = t.rpartition(sep)
        t = t.replace(sep, "") if len(dec) == 3 and entero else entero.replace(sep, "") + "." + dec
    return float(t)


class Decisor:
    def __init__(self, cfg: Config, almacen: Almacen, ia: IA, broker: Broker,
                 notificador: Notificador, http: httpx.AsyncClient):
        self.cfg = cfg
        self.db = almacen
        self.ia = ia
        self.broker = broker
        self.notif = notificador
        self.http = http
        self._tareas_fuente: dict[str, asyncio.Task] = {}
        self._fuentes_cfg: dict[str, FuenteCfg] = {}
        self._esperando_importe: int | None = None
        self._bloqueo_ordenes = asyncio.Lock()
        self._en_curso: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ fuentes
    def _todas_las_fuentes(self) -> list[FuenteCfg]:
        desactivadas = set(self.db.ajuste("fuentes_desactivadas", []))
        fuentes = [f for f in self.cfg.fuentes if f.activa and f.clave not in desactivadas]
        fuentes += [FuenteCfg.model_validate(d) for d in self.db.fuentes_extra()]
        return fuentes

    def _arrancar_fuente(self, fcfg: FuenteCfg) -> None:
        if fcfg.clave in self._tareas_fuente:
            return
        self._fuentes_cfg[fcfg.clave] = fcfg
        self._tareas_fuente[fcfg.clave] = asyncio.create_task(self._vigilar(fcfg), name=fcfg.clave)

    def _parar_fuente(self, clave: str) -> bool:
        tarea = self._tareas_fuente.pop(clave, None)
        self._fuentes_cfg.pop(clave, None)
        if tarea:
            tarea.cancel()
        return tarea is not None

    async def _vigilar(self, fcfg: FuenteCfg) -> None:
        try:
            fuente = sources.crear(fcfg, self.http, self.cfg.x_bearer_token)
        except sources.FuenteNoDisponible as e:
            await self.notif.enviar(f"⚠️ Fuente <b>{escape(fcfg.nombre)}</b> desactivada: {escape(str(e))}")
            return
        primera = True
        errores = 0
        while True:
            try:
                posts = await fuente.leer()
                errores = 0
                for post in sorted(posts, key=lambda p: p.publicado):
                    if self.db.ya_visto(post.clave, post.huella):
                        continue
                    self.db.marcar_visto(post.clave, post.huella)
                    if primera:
                        continue  # al arrancar no avisamos de lo ya publicado
                    self._lanzar(self.procesar(post))
                primera = False
                await asyncio.sleep(fcfg.intervalo_s)
            except asyncio.CancelledError:
                raise
            except sources.FuenteNoDisponible as e:
                await self.notif.enviar(f"⚠️ Fuente <b>{escape(fcfg.nombre)}</b> desactivada: {escape(str(e))}")
                return
            except sources.Limitada as e:
                log.warning("%s limitada, espero %.0fs", fcfg.clave, e.espera_s)
                await asyncio.sleep(e.espera_s)
            except Exception as e:
                errores += 1
                espera = min(fcfg.intervalo_s * 2 ** errores, 300)
                log.warning("Error en %s (%s), reintento en %.0fs", fcfg.clave, e, espera)
                if errores == 5:
                    await self.notif.enviar(
                        f"⚠️ La fuente <b>{escape(fcfg.nombre)}</b> falla repetidamente: {escape(str(e)[:200])}"
                    )
                await asyncio.sleep(espera)

    def _lanzar(self, coro) -> None:
        tarea = asyncio.create_task(coro)
        self._en_curso.add(tarea)
        tarea.add_done_callback(self._en_curso.discard)

    # ------------------------------------------------------------------ flujo principal
    async def procesar(self, post: Publicacion) -> int:
        id_ev = self.db.crear_evento(post)
        try:
            triaje = await self.ia.triaje(post)
        except ErrorIA as e:
            # Ante la duda, avisamos: perder una noticia importante es peor que un falso positivo.
            log.warning("Triaje fallido (%s); se analiza igualmente", e)
            triaje = Triaje(relevante=True, sorpresa_preliminar=50, alcance="macro",
                            titular="(triaje no disponible)", motivo=str(e))
        self.db.actualizar(id_ev, triaje=triaje, triaje_ts=datetime.now(timezone.utc).isoformat())
        if not triaje.relevante and triaje.sorpresa_preliminar < self.cfg.ia.umbral_relevancia:
            self.db.actualizar(id_ev, estado="descartado")
            log.info("Descartado [%s] %s: %s", post.autor, triaje.titular, triaje.motivo)
            return id_ev

        # Fase 1: aviso inmediato, sin esperar al análisis completo.
        await self.notif.enviar(
            f"⚡ <b>{escape(post.autor)}</b> · hace {_hace(post.publicado)}\n"
            f"<i>{escape(post.texto[:700])}</i>\n\n"
            f"🔎 {escape(triaje.titular)}\nSorpresa preliminar: {triaje.sorpresa_preliminar}/100 · analizando…"
        )
        self.db.actualizar(id_ev, aviso_ts=datetime.now(timezone.utc).isoformat())

        # Fase 2: contexto de mercado + análisis completo.
        try:
            variaciones = await asyncio.wait_for(
                self.broker.variacion_desde(self.cfg.mercado.referencia, post.publicado), timeout=10
            )
        except Exception as e:
            log.warning("Sin datos de mercado: %s", e)
            variaciones = {}
        mercado = (
            "Variación desde la publicación: " + ", ".join(f"{s} {v:+.2f}%" for s, v in variaciones.items())
            if variaciones else "Sin datos de precio disponibles."
        )
        previas = [(r["publicado"], r["texto"]) for r in self.db.recientes_de(post.autor, excluir=id_ev)]
        try:
            analisis = await self.ia.analizar(post, previas, mercado)
        except ErrorIA as e:
            self.db.actualizar(id_ev, estado="error", nota=str(e))
            await self.notif.enviar(f"⚠️ No pude analizar la publicación de {escape(post.autor)}: {escape(str(e))}")
            return id_ev
        ahora = datetime.now(timezone.utc)
        self.db.actualizar(id_ev, analisis=analisis, analisis_ts=ahora.isoformat())

        await self._presentar(id_ev, post, analisis)
        return id_ev

    async def _presentar(self, id_ev: int, post: Publicacion, a: Analisis) -> None:
        p = a.propuesta
        activos = "\n".join(
            f"{'🟢' if x.direccion == 'alcista' else '🔴'} <b>{escape(x.simbolo)}</b> – {escape(x.motivo)}"
            for x in a.activos_afectados[:6]
        ) or "—"
        texto = (
            f"📊 <b>Análisis</b> · {escape(post.autor)} · {a.alcance}\n\n"
            f"<b>Sorpresa</b> {_barra(a.sorpresa)}\n{escape(a.sorpresa_motivo)}\n\n"
            f"{escape(a.explicacion)}\n\n<b>Activos afectados</b>\n{activos}\n\n"
            f"<b>¿Ya cotizado?</b> {escape(a.ya_cotizado)}\n\n"
        )
        problemas = validar_propuesta(p, self.cfg.riesgo)
        if not p.operar:
            self.db.actualizar(id_ev, estado="sin_operacion")
            await self.notif.enviar(texto + f"💤 <b>Sin operación</b>: {escape(p.motivo)}")
            return

        flecha = "COMPRAR" if p.accion == "comprar" else "VENDER"
        texto += (
            f"💡 <b>Propuesta: {flecha} {escape(p.simbolo or '')}</b> ({p.tipo_instrumento})\n"
            f"Stop −{p.stop_pct}% · Objetivo +{p.objetivo_pct}% · Horizonte {p.horizonte_min} min\n"
            f"Convicción {_barra(p.conviccion)}\n{escape(p.motivo)}"
        )
        if problemas:
            self.db.actualizar(id_ev, estado="no_ejecutable", nota="; ".join(problemas))
            await self.notif.enviar(texto + "\n\n🚫 <b>No ejecutable automáticamente</b>:\n• " +
                                    "\n• ".join(escape(m) for m in problemas))
            return

        try:
            info = await self.broker.info(p.simbolo, p.tipo_instrumento)
            precio_ref = info.precio
        except Exception as e:
            log.warning("Sin precio para %s: %s", p.simbolo, e)
            precio_ref = None
        if precio_ref:
            texto += f"\nPrecio ahora: {precio_ref:g}"
        texto += f"\n\n⏳ Caduca en {self.cfg.riesgo.caducidad_min:.0f} min · modo <b>{self.cfg.modo}</b>"
        self.db.actualizar(id_ev, estado="propuesto", precio_ref=precio_ref)
        importes = [i for i in self.cfg.riesgo.importes_rapidos if i <= self.cfg.riesgo.max_por_operacion]
        teclado = [
            [Boton(f"✅ {i:,.0f} $", f"e:{id_ev}:{i:g}") for i in importes],
            [Boton("✏️ Otro importe", f"o:{id_ev}"), Boton("❌ No", f"n:{id_ev}")],
        ]
        await self.notif.enviar(texto, teclado)

    # ------------------------------------------------------------------ ejecución
    async def ejecutar(self, id_ev: int, importe: float) -> None:
        async with self._bloqueo_ordenes:
            ev = self.db.evento(id_ev)
            if ev is None:
                await self.notif.enviar("No encuentro esa propuesta.")
                return
            if ev["estado"] != "propuesto":
                await self.notif.enviar(f"La propuesta #{id_ev} ya no está pendiente (estado: {ev['estado']}).")
                return
            a = Analisis.model_validate_json(ev["analisis"])
            p = a.propuesta
            try:
                info = await self.broker.info(p.simbolo, p.tipo_instrumento)
                plan = planificar(
                    p, self.cfg.riesgo, importe=importe, precio_actual=info.precio,
                    precio_ref=ev["precio_ref"], propuesta_ts=datetime.fromisoformat(ev["analisis_ts"]),
                    importe_hoy=self.db.importe_ejecutado_hoy(), posiciones_abiertas=len(self.db.abiertos()),
                    pausado=bool(self.db.ajuste("pausado", False)), tick=info.tick,
                    multiplicador=info.multiplicador,
                )
            except Rechazo as r:
                if any("caducado" in m or "en contra" in m for m in r.motivos):
                    self.db.actualizar(id_ev, estado="caducado", nota=str(r))
                await self.notif.enviar(f"🚫 Orden #{id_ev} rechazada por el control de riesgo:\n• " +
                                        "\n• ".join(escape(m) for m in r.motivos))
                return
            resultado = await self.broker.enviar(plan)
            ahora = datetime.now(timezone.utc)
            if not resultado.ok:
                self.db.actualizar(id_ev, estado="error", nota=resultado.detalle)
                await self.notif.enviar(f"⚠️ IBKR no aceptó la orden #{id_ev}: {escape(resultado.detalle)}")
                return
            self.db.actualizar(
                id_ev, estado="ejecutado", decision_importe=importe, decision_ts=ahora.isoformat(),
                orden={"ref": resultado.referencia, "plan": plan.__dict__, "detalle": resultado.detalle,
                       "revisar_en": (ahora + timedelta(minutes=plan.horizonte_min)).isoformat()},
            )
            await self.notif.enviar(
                f"✅ Orden #{id_ev} enviada ({self.broker.nombre}):\n{escape(resultado.detalle)}\n"
                f"Te aviso en {plan.horizonte_min} min para revisar la posición.",
                [[Boton("🔚 Cerrar ya", f"c:{id_ev}")]],
            )

    async def cerrar(self, id_ev: int) -> None:
        async with self._bloqueo_ordenes:
            ev = self.db.evento(id_ev)
            if ev is None or ev["estado"] != "ejecutado":
                await self.notif.enviar(f"La operación #{id_ev} no está abierta.")
                return
            orden = json.loads(ev["orden"])
            res = await self.broker.cerrar_posicion(orden["ref"])
            if res.ok:
                self.db.actualizar(id_ev, estado="cerrado", nota=res.detalle)
            await self.notif.enviar(("🔚 " if res.ok else "⚠️ ") + escape(res.detalle))

    async def _vigilar_horizontes(self) -> None:
        while True:
            await asyncio.sleep(30)
            ahora = datetime.now(timezone.utc)
            for ev in self.db.abiertos():
                orden = json.loads(ev["orden"])
                if orden.get("avisado") or datetime.fromisoformat(orden["revisar_en"]) > ahora:
                    continue
                orden["avisado"] = True
                self.db.actualizar(ev["id"], orden=orden)
                plan = orden["plan"]
                await self.notif.enviar(
                    f"⏰ Horizonte cumplido para #{ev['id']}: {plan['accion']} {plan['cantidad']:g} "
                    f"{plan['simbolo']} (stop {plan['stop']}, objetivo {plan['objetivo']}).\n"
                    "¿Cierro la posición o la mantengo con sus órdenes de stop y objetivo?",
                    [[Boton("🔚 Cerrar ya", f"c:{ev['id']}"), Boton("⏳ Mantener", f"m:{ev['id']}")]],
                )

    # ------------------------------------------------------------------ interacción
    async def manejar(self, tipo: str, contenido: str) -> None:
        if tipo == "boton":
            await self._boton(contenido)
        elif tipo == "comando":
            await self._comando(contenido)
        elif tipo == "texto" and self._esperando_importe is not None:
            id_ev, self._esperando_importe = self._esperando_importe, None
            try:
                importe = leer_importe(contenido)
            except ValueError:
                await self.notif.enviar("No he entendido el importe. Pulsa de nuevo «Otro importe».")
                return
            await self.ejecutar(id_ev, importe)

    async def _boton(self, datos: str) -> None:
        partes = datos.split(":")
        accion, id_ev = partes[0], int(partes[1])
        if accion == "e":
            await self.ejecutar(id_ev, float(partes[2]))
        elif accion == "o":
            self._esperando_importe = id_ev
            await self.notif.enviar(f"Escribe el importe en $ para la propuesta #{id_ev} "
                                    f"(máximo {self.cfg.riesgo.max_por_operacion:,.0f}).")
        elif accion == "n":
            ev = self.db.evento(id_ev)
            if ev and ev["estado"] == "propuesto":
                self.db.actualizar(id_ev, estado="rechazado", decision_ts=datetime.now(timezone.utc).isoformat())
            await self.notif.enviar(f"👍 Propuesta #{id_ev} descartada.")
        elif accion == "c":
            await self.cerrar(id_ev)
        elif accion == "m":
            await self.notif.enviar(f"⏳ Mantengo #{id_ev} con su stop y su objetivo en IBKR.")

    async def _comando(self, texto: str) -> None:
        cmd, _, resto = texto.partition(" ")
        cmd = cmd.split("@")[0].lower()
        args = resto.split()
        if cmd in ("/start", "/ayuda", "/help"):
            await self.notif.enviar(AYUDA)
        elif cmd == "/fuentes":
            lineas = [f"• <b>{escape(f.nombre)}</b> – <code>{escape(f.clave)}</code> cada {f.intervalo_s:g}s"
                      for f in self._fuentes_cfg.values()]
            await self.notif.enviar("<b>Fuentes activas</b>\n" + ("\n".join(lineas) or "ninguna"))
        elif cmd == "/seguir":
            await self._seguir(args)
        elif cmd == "/dejar" and args:
            clave = args[0]
            parada = self._parar_fuente(clave)
            if not self.db.desactivar_fuente(clave):
                desactivadas = set(self.db.ajuste("fuentes_desactivadas", []))
                desactivadas.add(clave)
                self.db.fijar_ajuste("fuentes_desactivadas", sorted(desactivadas))
            await self.notif.enviar(f"{'✅ Dejo de seguir' if parada else 'No seguía'} <code>{escape(clave)}</code>")
        elif cmd == "/pausa":
            self.db.fijar_ajuste("pausado", True)
            await self.notif.enviar("⏸ Operativa en pausa. Seguirás recibiendo avisos y análisis.")
        elif cmd == "/reanudar":
            self.db.fijar_ajuste("pausado", False)
            await self.notif.enviar("▶️ Operativa reanudada.")
        elif cmd == "/estado":
            r = self.cfg.riesgo
            await self.notif.enviar(
                f"Modo: <b>{self.cfg.modo}</b> · bróker: {self.broker.nombre}\n"
                f"Operativa: {'⏸ en pausa' if self.db.ajuste('pausado', False) else '▶️ activa'}\n"
                f"Hoy: {self.db.importe_ejecutado_hoy():,.0f} / {r.max_diario:,.0f} $ · "
                f"abiertas: {len(self.db.abiertos())} / {r.max_posiciones_abiertas}\n"
                f"Máx. por operación: {r.max_por_operacion:,.0f} $ · fuentes: {len(self._fuentes_cfg)}"
            )
        elif cmd == "/posiciones":
            pos = await self.broker.posiciones()
            await self.notif.enviar("<b>Posiciones</b>\n" + ("\n".join(escape(p) for p in pos) or "ninguna"))
        elif cmd == "/ultimas":
            lineas = []
            for ev in self.db.ultimos(8):
                titular = json.loads(ev["triaje"])["titular"] if ev["triaje"] else ev["texto"][:60]
                lineas.append(f"#{ev['id']} [{ev['estado']}] {escape(ev['autor'])}: {escape(titular)}")
            await self.notif.enviar("\n".join(lineas) or "Sin eventos todavía.")
        elif cmd == "/probar" and resto.strip():
            post = Publicacion(fuente="prueba:manual", autor="Prueba manual", id_externo=str(datetime.now().timestamp()),
                               texto=resto.strip(), publicado=datetime.now(timezone.utc))
            self._lanzar(self.procesar(post))
        else:
            await self.notif.enviar("Comando no reconocido. /ayuda para ver la lista.")

    async def _seguir(self, args: list[str]) -> None:
        if len(args) < 2 or args[0] not in ("truth", "x", "rss"):
            await self.notif.enviar("Uso: /seguir truth|x|rss &lt;cuenta o url&gt; [nombre]")
            return
        tipo = {"truth": "truthsocial", "x": "x", "rss": "rss"}[args[0]]
        objetivo = args[1].lstrip("@")
        resto = args[2:]
        intervalo = {"truthsocial": 20, "x": 60, "rss": 60}[tipo]
        # "/seguir rss <url> Nombre cada 10" → cada 10 minutos
        if len(resto) >= 2 and resto[-2].lower() == "cada" and resto[-1].replace(".", "", 1).isdigit():
            intervalo = float(resto[-1]) * 60
            resto = resto[:-2]
        nombre = " ".join(resto) or objetivo
        datos = {"tipo": tipo, "nombre": nombre, "intervalo_s": intervalo}
        datos["url" if tipo == "rss" else "cuenta"] = objetivo
        fcfg = FuenteCfg.model_validate(datos)
        self.db.guardar_fuente(fcfg.clave, fcfg.model_dump())
        desactivadas = set(self.db.ajuste("fuentes_desactivadas", []))
        if fcfg.clave in desactivadas:
            desactivadas.discard(fcfg.clave)
            self.db.fijar_ajuste("fuentes_desactivadas", sorted(desactivadas))
        self._arrancar_fuente(fcfg)
        await self.notif.enviar(f"✅ Siguiendo <b>{escape(nombre)}</b> (<code>{escape(fcfg.clave)}</code>)")

    # ------------------------------------------------------------------ arranque
    async def ejecutar_siempre(self) -> None:
        await self.broker.conectar()
        for f in self._todas_las_fuentes():
            self._arrancar_fuente(f)
        await self.notif.enviar(
            f"🟢 Decisor arrancado · modo <b>{self.cfg.modo}</b> · {len(self._fuentes_cfg)} fuentes. /ayuda"
        )
        await asyncio.gather(self.notif.escuchar(self.manejar), self._vigilar_horizontes())
