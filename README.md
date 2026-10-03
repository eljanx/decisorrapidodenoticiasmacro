# Decisor rápido de noticias macro

Vigila en tiempo real publicaciones que pueden mover el mercado (Trump en Truth Social, la Fed, cuentas de X...), las analiza con Claude siguiendo un marco de decisión fijo y te propone una operación en Telegram. Si la aceptas, la lanza en Interactive Brokers con stop y objetivo.

El diseño completo y los riesgos están en [DISENO.md](DISENO.md).

```
Fuentes ──► triaje (¿relevante?) ──► ⚡ aviso inmediato en Telegram
                                      │
                       datos de mercado + publicaciones previas + búsqueda web
                                      ▼
                    📊 análisis: sorpresa · alcance · ¿ya cotizado? · explicación
                                      ▼
                    💡 propuesta ──► motor de riesgo (reglas fijas) ──► [✅ 500 $] [✅ 1.000 $] [✏️ Otro] [❌ No]
                                                                         ▼
                                              IBKR: orden límite + stop + objetivo (bracket)
                                                                         ▼
                                              ⏰ aviso al cumplirse el horizonte: [Cerrar] [Mantener]
```

## Qué hace cada paso

| Paso | Qué hace |
|---|---|
| Fuentes | Consulta Truth Social (API pública), RSS (respaldo de Truth Social, Fed...) y X (solo con API de pago). Elimina duplicados aunque el mismo post llegue por dos vías. |
| Triaje | Una llamada rápida a Claude decide si la publicación es relevante. Si no lo es, se registra y no te molesta. |
| Aviso | Te llega al momento, antes del análisis, para que no pierdas segundos. |
| Análisis | Pasos 0 a 4 del marco: sorpresa (0-100), relevancia, alcance y activos afectados, si el movimiento ya está en el precio, explicación y propuesta (que puede ser «no operar»). |
| Riesgo | Reglas deterministas: importes máximos por operación y por día, número de posiciones, instrumentos permitidos, stop obligatorio, caducidad y deslizamiento máximo del precio. La IA no puede saltárselas. |
| Ejecución | Orden límite con stop-loss y take-profit. Al cumplirse el horizonte te pregunta si cierras o mantienes. |

## Puesta en marcha

### 1. Requisitos
- Python 3.10 o superior.
- Una clave de la API de Anthropic ([console.anthropic.com](https://console.anthropic.com)). Es de pago por uso: cada publicación relevante cuesta unos céntimos. Las irrelevantes cuestan bastante menos.
- Telegram en el móvil.
- Para operar: IB Gateway (o TWS) de Interactive Brokers. **Empieza con la cuenta paper.**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
cp .env.example .env
```

### 2. Crear el bot de Telegram (5 minutos)
1. En Telegram, abre **@BotFather**, envía `/newbot` y elige un nombre. Te dará un token: pégalo en `.env` como `TELEGRAM_BOT_TOKEN`.
2. Arranca el decisor (paso 4) y escribe `/start` a tu bot. Te responderá con tu `chat_id`.
3. Pon ese número en `.env` como `TELEGRAM_CHAT_ID` y reinicia. El bot **solo obedece a ese chat**.

Sin Telegram también funciona: `python -m decisor --consola` muestra los avisos en la terminal, y los botones se «pulsan» escribiendo su código (por ejemplo `e:3:500`).

### 3. Conectar Interactive Brokers (cuando quieras pasar de `simulado`)
1. Instala IB Gateway y entra con tu usuario de **paper trading**.
2. En *Configure → Settings → API → Settings*: activa *Enable ActiveX and Socket Clients*, desactiva *Read-Only API* y comprueba que el puerto es `4002`.
3. En `config.yaml` pon `modo: paper`.
4. Para dinero real: IB Gateway con la cuenta real (puerto `4001`), `modo: real`, `ibkr.puerto: 4001` y `confirmo_dinero_real: true`.

Sin suscripción a datos en tiempo real, IBKR da precios con 15 minutos de retraso. Para operar minutos después de una noticia **necesitas datos en tiempo real**. El paquete básico de EE. UU. cuesta unos pocos dólares al mes (o es gratis si generas comisiones suficientes).

### 4. Arrancar
```bash
python -m decisor           # usa Telegram si está configurado
python -m decisor --consola # todo por terminal
```

Prueba el flujo sin esperar a que Trump publique algo:
```
/probar We are imposing a 100% tariff on all semiconductors coming into the United States
```

## Comandos de Telegram (panel de configuración)

| Comando | Para qué |
|---|---|
| `/fuentes` | Ver las fuentes vigiladas y su clave |
| `/seguir truth realDonaldTrump Trump` | Seguir una cuenta de Truth Social |
| `/seguir rss https://… Nombre` | Seguir un feed RSS (o un puente RSS de X) |
| `/seguir x cuenta` | Seguir una cuenta de X (requiere `X_BEARER_TOKEN` de pago) |
| `/dejar <clave>` | Dejar de seguir |
| `/pausa` y `/reanudar` | Interruptor de emergencia: bloquea las operaciones, pero los avisos siguen |
| `/estado`, `/posiciones`, `/ultimas` | Estado, posiciones en el bróker e historial |
| `/probar <texto>` | Simular una publicación |

Los límites de riesgo se ajustan en `config.yaml` (sección `riesgo`).

## Fuentes gratuitas: lo que hay que saber
- **Truth Social** no tiene API oficial. La app usa su API pública (tipo Mastodon) cada 5 segundos. Puede bloquearla Cloudflare. Si te pasa, el RSS de `trumpstruth.org` sirve de respaldo, aunque llega algo más tarde.
- **X**: el plan gratuito de la API no permite leer tweets. Las alternativas son el plan de pago por uso, o un puente RSS autoalojado (RSSHub) añadido con `/seguir rss`.
- **La latencia real se registra**: cada evento guarda en `decisor.db` cuándo se publicó, cuándo se detectó, cuándo se avisó y cuándo terminó el análisis. Revísalo tras unos días para saber cuánto tardas de verdad.

## Pruebas
```bash
pip install -r requirements-dev.txt
pytest
```

## Limitaciones de esta versión
- Las **opciones** se proponen, pero no se ejecutan de forma automática: elegir strike y vencimiento necesita más reglas. Hazlas a mano.
- Los importes van en **USD**.
- No mide aún el resultado de cada propuesta a 1 minuto, 15 minutos y 1 hora (fase 2 de [DISENO.md](DISENO.md)). Es imprescindible antes de usar dinero real.
- Ninguna salida de la IA es asesoramiento financiero. Empieza en `simulado` y `paper`.
