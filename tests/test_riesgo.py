from datetime import datetime, timedelta, timezone

import pytest

from decisor.config import RiesgoCfg
from decisor.modelos import Propuesta
from decisor.riesgo import Rechazo, planificar, validar_propuesta

AHORA = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)


def prop(**kw):
    base = dict(operar=True, simbolo="XLE", tipo_instrumento="etf", accion="comprar",
                stop_pct=1.0, objetivo_pct=2.0, horizonte_min=60, conviccion=70, motivo="test")
    base.update(kw)
    return Propuesta(**base)


def plan(p=None, **kw):
    args = dict(importe=1000, precio_actual=90.0, precio_ref=90.0, propuesta_ts=AHORA,
                importe_hoy=0, posiciones_abiertas=0, pausado=False, ahora=AHORA + timedelta(minutes=1))
    args.update(kw)
    return planificar(p or prop(), RiesgoCfg(), **args)


def test_plan_compra_valido():
    pl = plan()
    assert pl.accion == "BUY"
    assert pl.limite == pytest.approx(90.14)  # 90 * 1.0015 redondeado a tick
    assert pl.cantidad == 11  # floor(1000 / 90.14)
    assert pl.stop < pl.limite < pl.objetivo


def test_venta_en_corto_rechazada_por_defecto():
    assert any("corto" in m for m in validar_propuesta(prop(accion="vender"), RiesgoCfg()))


def test_venta_permitida_invierte_stop_y_objetivo():
    cfg = RiesgoCfg(permitir_cortos=True)
    pl = planificar(prop(accion="vender"), cfg, importe=1000, precio_actual=90.0, precio_ref=90.0,
                    propuesta_ts=AHORA, importe_hoy=0, posiciones_abiertas=0, pausado=False, ahora=AHORA)
    assert pl.accion == "SELL"
    assert pl.objetivo < pl.limite < pl.stop


@pytest.mark.parametrize("kw,texto", [
    ({"importe": 5000}, "máximo por operación"),
    ({"importe_hoy": 4500}, "máximo diario"),
    ({"posiciones_abiertas": 3}, "posiciones abiertas"),
    ({"pausado": True}, "pausa"),
    ({"ahora": AHORA + timedelta(minutes=30)}, "caducado"),
    ({"precio_actual": 91.0}, "en contra"),
])
def test_rechazos(kw, texto):
    with pytest.raises(Rechazo) as e:
        plan(**kw)
    assert any(texto in m for m in e.value.motivos)


def test_movimiento_a_favor_no_bloquea():
    assert plan(precio_actual=89.0).limite < 90


def test_stop_fuera_de_rango_y_conviccion_baja():
    motivos = validar_propuesta(prop(stop_pct=10, conviccion=10), RiesgoCfg())
    assert any("Stop" in m for m in motivos) and any("Convicción" in m for m in motivos)


def test_opciones_no_se_ejecutan_automaticamente():
    assert any("no permitido" in m for m in validar_propuesta(prop(tipo_instrumento="opcion"), RiesgoCfg()))


def test_futuros_cuentan_contratos_por_nocional():
    p = prop(simbolo="MES", tipo_instrumento="futuro")
    with pytest.raises(Rechazo, match="1 contrato"):
        plan(p, precio_actual=6500.0, precio_ref=6500.0, tick=0.25, multiplicador=5)
    cfg = RiesgoCfg(max_por_operacion=100000, max_diario=100000)
    pl = planificar(p, cfg, importe=70000, precio_actual=6500.0, precio_ref=6500.0, propuesta_ts=AHORA,
                    importe_hoy=0, posiciones_abiertas=0, pausado=False, tick=0.25, multiplicador=5, ahora=AHORA)
    assert pl.cantidad == 2
    assert (pl.limite / 0.25).is_integer()


def test_no_operar():
    assert validar_propuesta(prop(operar=False), RiesgoCfg()) == ["La IA recomienda no operar"]
