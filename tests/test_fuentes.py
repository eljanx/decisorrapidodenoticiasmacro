from datetime import datetime, timezone

from decisor.config import FuenteCfg
from decisor.modelos import Publicacion
from decisor.sources.rss import parsear
from decisor.sources.truthsocial import TruthSocial

FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Truths</title>
<item><title>Tariffs on China</title><link>https://example.org/1</link><guid>id-1</guid>
<description>&lt;p&gt;Tariffs on China will be 100% starting Nov 1!&lt;/p&gt;</description>
<pubDate>Fri, 10 Oct 2025 18:50:00 +0000</pubDate></item>
<item><title>Rally</title><link>https://example.org/2</link><guid>id-2</guid>
<description>Rally</description><pubDate>Fri, 10 Oct 2025 17:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_parsear_rss():
    posts = parsear(FEED, "rss:x", "Donald Trump")
    assert len(posts) == 2
    assert posts[0].id_externo == "id-1"
    assert "100%" in posts[0].texto and "<p>" not in posts[0].texto
    assert posts[0].publicado == datetime(2025, 10, 10, 18, 50, tzinfo=timezone.utc)


def test_truthsocial_estado_y_retruth():
    f = TruthSocial(FuenteCfg(tipo="truthsocial", cuenta="realDonaldTrump", nombre="Trump"), http=None)
    p = f._a_publicacion({"id": "115", "created_at": "2025-10-10T18:50:00.000Z", "url": "u",
                          "content": "<p>Hello &amp; goodbye</p>", "reblog": None})
    assert p.texto == "Hello & goodbye" and p.clave == "truthsocial:realDonaldTrump:115"
    p2 = f._a_publicacion({"id": "116", "created_at": "2025-10-10T18:51:00Z", "content": "",
                           "reblog": {"content": "<p>Big news</p>", "account": {"acct": "WhiteHouse"}}})
    assert p2.texto.startswith("[ReTruth de @WhiteHouse] Big news")
    p3 = f._a_publicacion({"id": "117", "created_at": "2025-10-10T18:52:00Z", "content": "",
                           "media_attachments": [{}]})
    assert "imagen" in p3.texto


def test_huella_ignora_urls_y_mayusculas():
    kw = dict(autor="Trump", publicado=datetime.now(timezone.utc))
    a = Publicacion(fuente="truthsocial:t", id_externo="1", texto="BIG tariffs! https://t.co/a", **kw)
    b = Publicacion(fuente="rss:t", id_externo="zz", texto="big tariffs", **kw)
    assert a.huella == b.huella and a.clave != b.clave
