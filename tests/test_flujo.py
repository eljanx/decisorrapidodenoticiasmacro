"""Flujo completo con IA falsa, bróker simulado y notificador en memoria."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from decisor.almacen import Almacen
from decisor.app import Decisor, leer_importe
from decisor.broker.simulado import Simulado
from decisor.config import Config
from decisor.ia import IA, ErrorIA, esquema
from decisor.modelos import Analisis, Publicacion, Triaje
from decisor.notifier.base import Notificador

ANALISIS = {
    "sorpresa": 85, "sorpresa_motivo": "No se esperaba", "relevante": True, "alcance": "sector",
    "activos_afectados": [{"simbolo": "XLE", "nombre": "Energía", "direccion": "alcista", "motivo": "petróleo"}],
    "ya_cotizado": "Parcialmente", "explicacion": "Explicación",
    "propuesta": {"operar": True, "simbolo": "XLE", "tipo_instrumento": "etf", "accion": "comprar",
                  "stop_pct": 1.0, "objetivo_pct": 2.0, "horizonte_min": 30, "conviccion": 70, "motivo": "m"},
}


class IAFalsa:
    def __init__(self, relevante=True, analisis=ANALISIS):
        self.relevante = relevante
        self.analisis = analisis

    async def triaje(self, post):
        return Triaje(relevante=self.relevante, sorpresa_preliminar=80 if self.relevante else 5,
                      alcance="sector", titular="Titular", motivo="m")

    async def analizar(self, post, previas, mercado):
        return Analisis.model_validate(self.analisis)


class Memoria(Notificador):
    def __init__(self):
        self.mensajes = []

    async def enviar(self, texto, teclado=None):
        self.mensajes.append((texto, teclado))
        return str(len(self.mensajes))

    async def editar(self, id_mensaje, texto, teclado=None):
        self.mensajes.append((texto, teclado))


def montar(tmp_path, ia=None, **cfg):
    notif = Memoria()
    d = Decisor(Config(base_datos=str(tmp_path / "t.db"), **cfg), Almacen(str(tmp_path / "t.db")),
                ia or IAFalsa(), Simulado({"XLE": 90.0}), notif, http=None)
    return d, notif


def post(texto="We will put tariffs on oil imports"):
    return Publicacion(fuente="prueba", autor="Trump", id_externo=texto[:10], texto=texto,
                       publicado=datetime.now(timezone.utc))


def test_flujo_propuesta_y_ejecucion(tmp_path):
    async def run():
        d, notif = montar(tmp_path)
        id_ev = await d.procesar(post())
        assert d.db.evento(id_ev)["estado"] == "propuesto"
        texto, teclado = notif.mensajes[-1]
        assert "COMPRAR XLE" in texto
        codigos = [b.datos for fila in teclado for b in fila]
        assert f"e:{id_ev}:500" in codigos and f"n:{id_ev}" in codigos

        await d.manejar("boton", f"e:{id_ev}:500")
        ev = d.db.evento(id_ev)
        assert ev["estado"] == "ejecutado" and ev["decision_importe"] == 500
        assert json.loads(ev["orden"])["plan"]["cantidad"] == 5  # 500 / 90.14

        # Doble clic: no se ejecuta dos veces
        await d.manejar("boton", f"e:{id_ev}:500")
        assert "ya no está pendiente" in notif.mensajes[-1][0]

        await d.manejar("boton", f"c:{id_ev}")
        assert d.db.evento(id_ev)["estado"] == "cerrado"

    asyncio.run(run())


def test_otro_importe_por_texto(tmp_path):
    async def run():
        d, notif = montar(tmp_path)
        id_ev = await d.procesar(post())
        await d.manejar("boton", f"o:{id_ev}")
        await d.manejar("texto", "1.000")
        assert d.db.evento(id_ev)["decision_importe"] == 1000

    asyncio.run(run())


def test_irrelevante_no_avisa(tmp_path):
    async def run():
        d, notif = montar(tmp_path, ia=IAFalsa(relevante=False))
        id_ev = await d.procesar(post("Happy birthday!"))
        assert d.db.evento(id_ev)["estado"] == "descartado"
        assert notif.mensajes == []

    asyncio.run(run())


def test_pausa_bloquea_ejecucion(tmp_path):
    async def run():
        d, notif = montar(tmp_path)
        id_ev = await d.procesar(post())
        await d.manejar("comando", "/pausa")
        await d.manejar("boton", f"e:{id_ev}:500")
        assert d.db.evento(id_ev)["estado"] == "propuesto"
        assert "pausa" in notif.mensajes[-1][0]

    asyncio.run(run())


def test_opcion_se_muestra_pero_no_es_ejecutable(tmp_path):
    a = json.loads(json.dumps(ANALISIS))
    a["propuesta"]["tipo_instrumento"] = "opcion"

    async def run():
        d, notif = montar(tmp_path, ia=IAFalsa(analisis=a))
        id_ev = await d.procesar(post())
        assert d.db.evento(id_ev)["estado"] == "no_ejecutable"
        assert notif.mensajes[-1][1] is None  # sin botones

    asyncio.run(run())


def test_seguir_y_dejar_fuentes(tmp_path):
    async def run():
        d, notif = montar(tmp_path)
        d._arrancar_fuente = lambda f: d._fuentes_cfg.__setitem__(f.clave, f)
        await d.manejar("comando", "/seguir truth @WhiteHouse Casa Blanca")
        assert "truthsocial:WhiteHouse" in d._fuentes_cfg
        assert d.db.fuentes_extra()[0]["nombre"] == "Casa Blanca"
        await d.manejar("comando", "/seguir rss https://www.whitehouse.gov/news/feed/ Casa Blanca cada 10")
        f = d._fuentes_cfg["rss:https://www.whitehouse.gov/news/feed/"]
        assert f.intervalo_s == 600 and f.nombre == "Casa Blanca"
        await d.manejar("comando", "/dejar truthsocial:WhiteHouse")
        assert [x["nombre"] for x in d.db.fuentes_extra()] == ["Casa Blanca"]

    asyncio.run(run())


@pytest.mark.parametrize("txt,valor", [("1500", 1500), ("1.500", 1500), ("1,500", 1500), ("1500,5", 1500.5),
                                       ("1500.5", 1500.5), ("$2.000", 2000), ("1.234,56", 1234.56)])
def test_leer_importe(txt, valor):
    assert leer_importe(txt) == pytest.approx(valor)


# --- capa de IA con un cliente falso (sin red) ---------------------------------

def test_esquema_compatible_con_salidas_estructuradas():
    s = json.dumps(esquema(Analisis))
    assert "minimum" not in s and "maximum" not in s
    e = esquema(Triaje)
    assert e["additionalProperties"] is False and set(e["required"]) == set(e["properties"])


class ClienteFalso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.llamadas.append(kw)
        return self.respuestas.pop(0)


def resp(stop="end_turn", texto=None):
    contenido = [SimpleNamespace(type="text", text=texto)] if texto else []
    return SimpleNamespace(stop_reason=stop, content=contenido)


def test_ia_triaje_y_pause_turn():
    from decisor.config import IACfg
    t = json.dumps({"relevante": True, "sorpresa_preliminar": 70, "alcance": "macro", "titular": "x", "motivo": "y"})
    cli = ClienteFalso([resp("pause_turn"), resp(texto=t)])
    out = asyncio.run(IA(IACfg(), cli).triaje(post()))
    assert out.relevante and len(cli.llamadas) == 2
    assert cli.llamadas[0]["fallbacks"] == "default"
    assert cli.llamadas[0]["output_config"]["format"]["type"] == "json_schema"


def test_ia_rechazo_y_json_invalido():
    from decisor.config import IACfg
    with pytest.raises(ErrorIA, match="rechazó"):
        asyncio.run(IA(IACfg(), ClienteFalso([resp("refusal")])).triaje(post()))
    with pytest.raises(ErrorIA):
        asyncio.run(IA(IACfg(), ClienteFalso([resp(texto="no json")])).triaje(post()))


def test_ia_error_de_api_se_convierte_en_error_ia():
    import anthropic
    import httpx2
    from decisor.config import IACfg

    class SinSaldo(ClienteFalso):
        async def _create(self, **kw):
            r = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
            raise anthropic.BadRequestError("Your credit balance is too low", response=r, body=None)

    with pytest.raises(ErrorIA, match="Sin saldo"):
        asyncio.run(IA(IACfg(), SinSaldo([])).triaje(post()))


def test_vigilar_no_avisa_de_lo_antiguo_y_muestra_estado(tmp_path, monkeypatch):
    from datetime import timedelta

    from decisor import sources
    from decisor.config import FuenteCfg

    ahora = datetime.now(timezone.utc)
    viejo = Publicacion(fuente="f", autor="Trump", id_externo="1", texto="viejo", publicado=ahora - timedelta(hours=3))
    nuevo = Publicacion(fuente="f", autor="Trump", id_externo="2", texto="nuevo", publicado=ahora)
    lecturas = [[], [viejo], [viejo, nuevo]]  # 1ª vacía (limitada), 2ª historial, 3ª novedad

    class Falsa:
        async def leer(self):
            if not lecturas:
                raise asyncio.CancelledError
            return lecturas.pop(0)

    monkeypatch.setattr(sources, "crear", lambda *a, **k: Falsa())

    async def run():
        d, notif = montar(tmp_path)
        procesados = []

        async def procesar(post):
            procesados.append(post.texto)

        d.procesar = procesar
        fcfg = FuenteCfg(tipo="rss", url="http://x", nombre="Prueba", intervalo_s=0)
        d._fuentes_cfg[fcfg.clave] = fcfg
        with pytest.raises(asyncio.CancelledError):
            await d._vigilar(fcfg)
        await asyncio.sleep(0)
        assert procesados == ["nuevo"]
        informe = d.informe_fuentes()
        assert "✅" in informe and "nuevo" in informe

    asyncio.run(run())
