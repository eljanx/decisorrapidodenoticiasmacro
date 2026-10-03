# Decisor rápido de noticias macro: diseño y challenge

> Estado: borrador de diseño, antes de escribir código.
> Objetivo: detectar en tiempo real publicaciones de cuentas que mueven mercado, analizarlas con un framework fijo, proponer una operación y ejecutarla en Interactive Brokers (IBKR) cuando el usuario la confirme.

---

## 1. Challenge: lo que hay que tener claro antes de construir

### 1.1 Trump publica casi todo primero en Truth Social, no en X
Sus mensajes que mueven mercado (aranceles, la Fed, la pausa arancelaria del 9-abr-2025) salen en **Truth Social**. A X llegan más tarde o como captura, si llegan. Si solo escuchamos X, nos enteraremos tarde de lo más importante.
- **Decisión**: la app tiene que funcionar con *fuentes* intercambiables (X, Truth Social, RSS de la Casa Blanca/Fed/BCE, newswires), no solo con X.
- Truth Social no tiene API oficial. Está basado en Mastodon y tiene endpoints públicos que se pueden consultar con polling (por ejemplo con la librería `truthbrush`). Es frágil: hay rate limits y Cloudflare, y puede romperse sin previo aviso.

### 1.2 X en tiempo real cuesta dinero
- Para un stream filtrado de verdad (con push, sin polling) hace falta la API de pago de X (filtered stream). Los planes y precios han cambiado varias veces (Basic, Pro, pago por uso); **hay que comprobar el precio vigente antes de comprometerse**. El nivel gratuito no sirve para esto.
- Alternativas: proveedores de terceros (por ejemplo, los servicios de "tweet monitoring" que hay por webhooks) o scraping. El scraping viola los términos de X y se rompe a menudo.

### 1.3 No vamos a ganar a los algoritmos en velocidad, y eso cambia el objetivo
Los fondos HFT y los bots leen estos posts en milisegundos y operan futuros (ES, NQ), divisas y bonos antes de que a nosotros nos llegue la notificación. Con un humano que lee, decide y confirma, nuestra latencia realista está entre **10 y 60 segundos** en el mejor caso.
- **Conclusión**: la ventaja de la app **no puede ser ser el primero**. Las ventajas realistas son:
  1. **Disciplina**: aplicar un framework fijo en lugar de reaccionar en caliente.
  2. **Efectos de segundo orden**: el mercado cotiza al instante el movimiento obvio (aranceles a China, el índice cae). Lo que tarda horas o días suele ser el efecto en sectores o empresas concretas (proveedores, sustitutos, exportadores).
  3. **Detectar sobrerreacciones**: identificar cuándo el primer movimiento se ha pasado y tiene sentido apostar a la reversión.
  4. **Filtrar el ruido**: el 95 % de los posts no importan, y la app te ahorra mirarlos.
- "Muy rápido" sigue siendo importante, pero como **segundos, no minutos**, no como competir con HFT.

### 1.4 El paso 0 (¿era esperado?) es el más valioso y el más difícil
Para saber si algo es inesperado hay que tener una **referencia de lo que el mercado esperaba**. Un LLM sin contexto se lo inventa. Fuentes posibles:
- Posts recientes del mismo autor (¿ya lo había anunciado?).
- Titulares de las últimas 24 a 72 horas sobre el tema.
- Calendario macro y de eventos (reuniones de la Fed, fechas límite arancelarias).
- Mercados de predicción (Polymarket, Kalshi): son una medida directa de la probabilidad que se le daba al evento.
- Movimiento del precio en los primeros segundos (si SPY o ES ya se ha movido un 1 %, el mercado lo ha leído como sorpresa).

### 1.5 Riesgos de seguridad: un tweet que puede lanzar órdenes
El texto del post entra directamente en el prompt de un LLM que propone operaciones. Eso es una vía de **prompt injection**: una cuenta comprometida o un post diseñado para ello podría manipular la propuesta.
- El LLM **nunca** ejecuta órdenes: solo devuelve una propuesta estructurada (JSON).
- La orden la construye código determinista con **límites duros**: tamaño máximo, lista blanca de instrumentos, solo órdenes limitadas y stop-loss obligatorio.
- Siempre hay confirmación humana explícita. Nada se ejecuta solo, al menos en las primeras versiones.
- Verificación de la fuente: comprobar el ID de la cuenta (no solo el nombre), y detectar cuentas parodia y posts borrados.

### 1.6 Regulación
- **Uso personal**: sin problema.
- **Si otros usuarios la usan** (aunque sean amigos): proponer operaciones concretas a terceros es **asesoramiento de inversión** (MiFID II, y en España la CNMV) y requiere licencia. Además, IBKR exige un proceso de *third-party vendor* para conectar cuentas de otros clientes.
- **Recomendación**: diseñarla como herramienta personal y de un único usuario.

### 1.7 El conector MCP de IBKR no es una API para el backend
El MCP de IBKR está pensado para que un asistente como Claude opere en nombre del usuario en una conversación. Su `create_order_instruction` crea *instrucciones de orden* que normalmente el usuario confirma desde IBKR. Un backend que corre 24/7 necesita otra cosa:
- **IB Gateway + TWS API** (librería `ib_async`, sucesora de `ib_insync`): la opción más rápida y fiable para uso personal. El gateway se ejecuta en tu servidor.
- **Client Portal Web API** (REST): más sencilla, pero las sesiones caducan y exige reautenticación periódica.
- El MCP **sí** encaja como segunda vía: preguntarle a Claude "revisa mi cartera y la propuesta de esta alerta" desde la propia conversación.

### 1.8 Sin medición no hay ventaja
Antes de poner dinero real hay que **registrar cada alerta, la propuesta y lo que hizo el mercado** a 1 minuto, 15 minutos, 1 hora y 1 día. Si después de dos o tres meses en *paper trading* las propuestas no ganan a "no hacer nada", la app no tiene ventaja. Además, hay que hacer un **backtest** con posts históricos de Trump (hay archivos públicos) y precios intradía para calibrar el framework.

---

## 2. Framework de decisión (revisado)

Cada paso produce un campo estructurado, no solo texto:

| Paso | Salida | Notas |
|---|---|---|
| 0. Sorpresa | `sorpresa: 0-100` y su justificación | Con la referencia de contexto del apartado 1.4. Un valor alto da más prioridad a la alerta. |
| 1. Relevancia | `relevante: bool` y `confianza` | Filtro rápido: si no es relevante, se descarta sin notificar. |
| 2. Alcance | `alcance: macro / sector / empresa`, `activos_afectados[]` con dirección (+/−) | Incluye efectos de segundo orden. |
| 2b. ¿Ya cotizado? | Movimiento observado desde el post en los activos afectados | **Paso nuevo**: si ya se ha movido mucho, puede que la propuesta sea no entrar o apostar a la reversión. |
| 3. Explicación | Texto breve: qué ha dicho, por qué lo dice (contexto) y cómo puede afectar | Con enlaces a las fuentes. |
| 4. Propuesta | `instrumento, dirección, tipo de orden, límite, stop, objetivo, horizonte, tamaño sugerido, convicción` | Validada por las reglas de riesgo del apartado 1.5. Puede ser "no operar". |
| 5. Decisión | El usuario acepta, modifica el importe o rechaza | Con un tiempo de caducidad: si el precio se ha movido más de X %, la propuesta se invalida. |
| 6. Ejecución | Orden enviada a IBKR con un bracket (entrada, stop y objetivo) | Confirmación y seguimiento de la posición. |

---

## 3. Arquitectura propuesta

```
 [Fuentes]                [Núcleo]                                   [Usuario]
 X filtered stream ─┐
 Truth Social poll ─┼─► Ingesta ─► Normaliza ─► Triaje rápido ─┬─► descartado (log)
 RSS / newswires  ──┘   + dedupe    + verifica   (LLM pequeño,  │
                                     autor        <1 s)          └─► Push inmediato "⚡ Trump: …"
                                                                      │
                          Contexto (posts previos, titulares,          ▼
                          Polymarket, precio en vivo) ─────► Análisis profundo (LLM grande,
                                                              streaming 5-15 s)
                                                                      │
                                                                      ▼
                                                              Motor de riesgo (determinista)
                                                                      │
                                                                      ▼
                                                              Propuesta ─► App / Telegram
                                                                      │   [Comprar 1.000 €] [Otro] [No]
                                                                      ▼
                                                              Ejecutor IBKR (IB Gateway)
                                                                      │
                                                              Registro y evaluación (BD)
```

**Presupuesto de latencia (objetivo)**

| Tramo | Objetivo |
|---|---|
| Publicación hasta que la ingesta la recibe | 1-3 s (stream) / 2-5 s (polling) |
| Triaje (relevante / no relevante) | < 1 s |
| Primera notificación push | < 5 s desde la publicación |
| Análisis completo y propuesta | < 20 s desde la publicación |
| Ejecución tras confirmar | < 1 s |

Clave de diseño: **dos fases**. Una alerta inmediata ("ha publicado esto y parece relevante") y, a continuación, el análisis completo. No hay que esperar al análisis para avisar.

**Stack sugerido para el MVP**
- Backend en Python (asyncio): un worker por fuente y una cola en memoria (Redis cuando haga falta).
- LLM: modelo pequeño y rápido para el triaje (por ejemplo, `claude-haiku-4-5`) y modelo grande para el análisis (por ejemplo, `claude-sonnet-5-5` o `claude-opus-5-5`), con salida estructurada por JSON schema y prompt caching del framework.
- Precios: datos de mercado de IBKR (ya vienen con la cuenta) para el paso 2b.
- Interfaz del MVP: **un bot de Telegram**. Las notificaciones push y los botones inline salen gratis, funciona en el móvil y no requiere publicar una app en las tiendas. La app nativa o web viene después.
- Panel de configuración: cuentas a seguir (handle, ID verificado, peso o prioridad), umbrales de relevancia y sorpresa, instrumentos permitidos, importe máximo por operación y por día, y horario.
- Base de datos: SQLite o Postgres con posts, análisis, propuestas, decisiones, órdenes y resultados.
- Despliegue: un VPS pequeño, siempre encendido, cerca de EE. UU. (us-east) e IB Gateway en el mismo servidor.

---

## 4. Plan por fases

1. **Fase 0, validación (1-2 semanas)**: backtest con los posts históricos de Trump de 2025 y la reacción intradía de SPY/ES/sectores. ¿El framework habría acertado? ¿Cuánto tiempo hubo para entrar?
2. **Fase 1, solo alertas**: ingesta de Truth Social y de X, triaje y bot de Telegram con la explicación. Sin propuestas de operación. Se mide la latencia real.
3. **Fase 2, propuestas en paper trading**: propuesta, botones y ejecución en una **cuenta paper de IBKR**. Se registran los resultados.
4. **Fase 3, dinero real con límites estrictos**: importes pequeños, lista blanca de ETFs líquidos (SPY, QQQ, sectoriales XL*), stop obligatorio y límite de pérdida diaria.
5. **Fase 4**: más fuentes (Fed, BCE, newswires), app propia y opciones o futuros.

---

## 5. Preguntas abiertas para el usuario

1. ¿Es para uso **personal** o quieres que la usen otras personas? (Afecta a la regulación y a la integración con IBKR.)
2. ¿Qué **instrumentos** quieres operar: acciones y ETFs, futuros, opciones o divisas? ¿Y en qué horario (fuera de mercado regular solo se puede operar con futuros o en premarket con poca liquidez)?
3. ¿Qué **presupuesto mensual** aceptas para las APIs (X, LLM, datos)?
4. ¿Te vale **Telegram** como interfaz en el MVP o necesitas desde el principio una app propia?
5. ¿Qué **horizonte** buscas: minutos (scalping de la noticia) u horas o días (efectos de segundo orden)? Mi recomendación es horas o días, por lo explicado en el apartado 1.3.

---

## 6. Decisiones tomadas (respuestas del usuario, 3-oct-2026)

| Pregunta | Respuesta | Consecuencia en la v1 |
|---|---|---|
| Uso | Personal | Un único usuario. El bot de Telegram solo obedece a un `chat_id`. |
| Instrumentos | Todos | Ejecución automática de acciones, ETFs, futuros (contrato continuo) y divisas. Las opciones se proponen pero se ejecutan a mano. |
| Presupuesto | APIs gratuitas para empezar | Truth Social por API pública con polling y RSS de respaldo. X desactivado salvo token de pago. Claude sí es de pago (céntimos por análisis). |
| Interfaz | Telegram (lo instalará) | Bot con botones. Modo `--consola` para probar sin Telegram. |
| Horizonte | Comprar minutos después y mantener lo que la app considere | La IA propone el horizonte. La orden lleva stop y objetivo (bracket) y, al cumplirse el horizonte, la app pregunta si cerrar o mantener. |

**Aviso sobre el horizonte de minutos**: es justo la franja en la que más compiten los algoritmos (apartado 1.3). Por eso la IA recibe la variación de precio desde la publicación (paso 2b) y puede recomendar no operar o buscar efectos de segundo orden. Hay que medir los resultados en paper antes de usar dinero real.
