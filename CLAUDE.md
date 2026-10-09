# Proyecto: Bot de Telegram — Diagramas de sistemas de medida de energía

## Qué es
Bot de Telegram que actúa como ingeniero de diseño eléctrico. Recibe las
especificaciones de una medida (texto libre, comando o menú) y devuelve:
- **Diagrama de conexiones** (Medidor ↔ Bloque de prueba ↔ TC/TP)
- **Diagrama unifilar** (con símbolos IEC/UNE 60617 y plano de simbología)

## Estructura
- `diagram_engine.py` — motor de dibujo (matplotlib). Funciones REALMENTE usadas
  por `bot.py` en producción (ver `_generar()`):
  - `draw_conexiones_retie(cfg, out)` → diagrama de conexiones (bloque de
    pruebas + terminales). Internamente despacha a `_draw_directa_retie` o
    `_draw_semi_indirecta_retie` según `cfg['tipo']`.
  - `draw_unifilar_generico(cfg, out)` → diagrama unifilar (todos los tipos:
    directa/semidirecta/indirecta, con o sin trafo, con o sin respaldo).
    (Las funciones legacy `draw`, `draw_unifilar`, `draw_unifilar_trafo` que
    existían aquí se eliminaron en la limpieza de QA — ver "QA de sept/2026"
    más abajo. Si vas a tocar el motor de unifilares, edita
    `draw_unifilar_generico`, la única función real.)
  - `draw_unifilar_gabinete(cfg, out)` → unifilar HORIZONTAL de medida DIRECTA en un punto/gabinete COMPARTIDO (lo despacha
    `draw_unifilar_generico`; ver sección "Unifilar de gabinete compartido").
  - `draw_unifilar_indirecta_pro(cfg, out)` → unifilar de indirecta en estilo "plano limpio" (lo despacha `draw_unifilar_generico`; ver sección "Unifilar de medida INDIRECTA en estilo ...").
  - Símbolos IEC: `_u_breaker, _u_disc, _u_fuse, _u_arrester, _u_ct, _u_vt, _u_xfmr, _u_relay, _ground`.
- `parser.py` — `parse_spec(text)` → `(cfg, entendido, faltante)`. Sin dependencias.
- `bot.py` — handlers de Telegram (start/help/menu/diagrama + texto libre + botones).
  `_verificar_coherencia(cfg)` corrige/advierte inconsistencias (p.ej. v_mt en
  tipos BT, trafo sin `trafo_uso`) ANTES de dibujar; `_verificar_render()`
  confirma que el PNG generado no salió vacío/corrupto antes de enviarlo.
- `test_e2e.py`, `test_menu_flow.py`, `test_parser_fields.py` — pruebas locales
  sin Telegram, contra las funciones reales de producción (no las legacy).
  OJO: `test_menu_flow.py` solo llama al motor, NO recorre el menú de botones.
- `test_menu_walk.py` — recorre el menú de botones REAL (`on_button`/`on_text`
  con objetos de Telegram simulados) por todos los tipo × salida y falla si
  algún camino queda sin respuesta. `--draw` además dibuja cada diagrama.
- `test_conexiones.py` — geometria del diagrama de conexiones (sin solapes, reglas in/cierre,
  barra BN). `test_pdf.py` — PDF -> unifilar. `test_claude_sdk.py` — llamadas a Claude con el SDK real.
- `test_gabinete.py` — plano de gabinete compartido de punta a punta: FIDELIDAD textual con el script del ejemplo, posición del medidor,
  26 variantes dibujadas sin textos superpuestos (detector de `test_frontera`; `GAB_OUT=<dir>` guarda los PNG), despacho, parser,
  trafo trifásico + medida mono/bifásica, `_completar_con_parser`, diálogo IA con el SDK real y correcciones después de un diagrama.
- `test_frontera.py` — campos de acta (varios transformadores, planta de respaldo, celda de medida,
  ubicacion de la medida): helpers, escenarios e–p (`FRONTERA_OUT=<dir>` guarda los PNG) y un
  detector de textos superpuestos (texto/texto, texto/cable, texto/borde de recuadro).
- `requirements.txt`, `README.md`.

## Velocidad y timeouts en las llamadas a Gemini
Las 3 funciones que llaman a Gemini (`_consulta_retie`, `_dialogo_diagrama`,
`_analizar_foto_cx`) envuelven CADA `generate_content` en
`asyncio.wait_for(..., timeout=GEMINI_TIMEOUT_S)` (25s). Motivo real: el
prompt del sistema creció mucho (varios bloques de "datos memorizados" +
reglas de precisión) y sumado al historial de conversación, una llamada
lenta podía quedar colgada sin que `except Exception` la atrapara a tiempo
— el usuario se quedaba sin ninguna respuesta ("se traba"). Si agregas un
nuevo punto de llamada a Gemini, envuélvelo igual: NUNCA dejes una llamada
sin timeout, sin importar que "debería responder rápido". `GenerateContentConfig`
también lleva `max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS` (1400) en las tres —
respuestas más cortas = generación más rápida, además de ser lo que pidió
el usuario ("más rápido y conciso"). `RETIE_HISTORIAL_MAX` se bajó de 8 a 4
(de ~4 a ~2 intercambios) por el mismo motivo: el prompt del sistema ya es
grande, un historial largo lo hace más lento sin ganar mucha precisión.

**Bug real que motivó subir el limite a 1400 y agregar `GEMINI_THINKING_CONFIG`:**
`gemini-2.5-flash` tiene "thinking" (razonamiento interno, invisible para el
usuario) activado por defecto, y ese razonamiento se descuenta del MISMO
presupuesto de `max_output_tokens` que la respuesta visible. Con el limite
en 900 y una pregunta de seguimiento (mas contexto en el historial = mas
"pensamiento"), el modelo a veces agotaba el presupuesto completo pensando
y terminaba con `finish_reason=MAX_TOKENS` y `response.text` vacio — el bot
respondia "El modelo no pudo generar una respuesta para esta consulta",
sin haber generado nunca una respuesta real. El retry que ya existia solo
cubria `finish_reason` con `"RECITATION"`, no `MAX_TOKENS`, asi que caia
directo al mensaje de error. Arreglo (dos partes, no una sola):
1. `GEMINI_THINKING_CONFIG = types.ThinkingConfig(thinking_budget=0)`
   aplicado en las 3 llamadas — desactiva el thinking extendido. Para
   preguntas/respuestas normativas directas no hace falta esa cadena de
   razonamiento; desactivarla es MAS RAPIDO (alineado con "mas rapido") y
   deja todo el presupuesto de tokens para la respuesta visible.
2. Subir `GEMINI_MAX_OUTPUT_TOKENS` de 900 a 1400 como margen adicional,
   y en `_consulta_retie` agregar un segundo camino de retry (junto al de
   RECITATION) que detecta `finish_reason` con `"MAX_TOKENS"` y reintenta
   una vez con el doble de presupuesto — defensa adicional por si alguna
   respuesta larga por si misma (no por thinking) vuelve a agotar el limite.
Si agregas un nuevo punto de llamada a Gemini para Q&A/dialogo (no para
generación de contenido largo), aplícale `thinking_config=GEMINI_THINKING_CONFIG`
también — si necesitas thinking extendido para algo especifico (ej. un
razonamiento multi-paso complejo), usa un `thinking_budget` explicito mayor
que 0 en vez de omitir el parametro, para no volver a caer en el mismo bug.

**Timeout: reintentar en vez de rendirse a la primera.** `_consulta_retie` y
`_dialogo_diagrama` antes trataban un `asyncio.TimeoutError` como definitivo
(`break` inmediato, sin reintentar) — la logica era "una consulta grande
volvera a tardar igual", pero en la practica esto le daba al usuario un
mensaje que le echaba la culpa a SU pregunta ("intenta con una pregunta mas
corta y especifica") cuando el problema real era una lentitud puntual del
servicio, no la consulta. Con `thinking_budget=0` un timeout ya deberia ser
la excepcion, no la regla, asi que ahora ambas funciones reintentan el
timeout igual que reintentan un 503/sobrecarga (hasta 3 intentos totales)
antes de mostrar el mensaje de error — y el mensaje final ya no sugiere que
la pregunta del usuario fue el problema. Si agregas un nuevo punto de
llamada con reintentos, aplica el mismo criterio: un timeout no es motivo
automatico para rendirse en el primer intento.

## Precisión en `PROMPT_SISTEMA_RETIE` (consultas normativas por IA)
- Regla de comportamiento: el bot debe responder EXACTAMENTE lo preguntado; si
  la pregunta es ambigua o la respuesta depende de una condición no
  especificada (ej. conexión nueva vs. instalación existente), debe enumerar
  las interpretaciones y responder cada una — nunca elegir una sola por su
  cuenta ni reducir una regla condicionada a un único número.
- Dato verificado (no repitas sin citar la fuente real): el umbral de **15
  kVA** que circula para "transformador exclusivo → medida indirecta" viene
  de la **Res. CREG 015/2018, Art. 3** (modificado por CREG 036/2019) —
  define qué transformadores de conexión ≤15 kVA que alimentan a 2+ usuarios
  cuentan como **activo de Nivel de Tensión 1** (clasificación de activos
  para remuneración). Es un criterio de clasificación de ACTIVOS, no la regla
  que decide si la medida es indirecta. Esa regla es el **Art. 19, CREG
  038/2014**: si la conexión es a través de un transformador, el punto de
  medida va en el lado de ALTA — aplica de lleno a conexiones NUEVAS con
  transformador exclusivo, independiente del kVA exacto. Para instalaciones
  YA EXISTENTES no hay migración automática solo por superar 15 kVA (hay que
  evaluar fecha de instalación, si cambia el sistema de medición, y si la
  capacidad técnica sube >50%). Si vas a agregar más "hechos memorizados"
  regulatorios al prompt, verifica el texto contra la fuente primaria
  (gestornormativo.creg.gov.co) antes de darlo por bueno — un dato citado por
  otra IA sin verificar es exactamente el tipo de error que este proyecto ya
  sufrió (ver el resto de este documento).
- **Datos agregados sept/2026** (verificados contra gestornormativo.creg.gov.co
  y fuentes que lo citan directamente, no una IA sin verificar):
  - **Resolución 40284 de 2026 (MinMinas) modifica el RETIE** — vigente desde
    el 1 jul/2026. NO reemplaza la 40117/2024, la ajusta. Cambios que sí le
    importan a este bot: técnicos electricistas ahora pueden hacer esquemas
    de hasta 4 cuentas de energía (antes 1) en vivienda uni/bifamiliar o
    pequeño comercio ≤15 kVA/240V; autogeneración a pequeña escala (AGPE)
    <10 kVA conectada a red queda exenta de certificación plena (pero no de
    cumplir el RETIE). Si el usuario pregunta por RETIE vigente, la respuesta
    ya no es solo "Resolución 40117/2024" — hay que mencionar esta
    modificación cuando sea relevante a la pregunta.
  - **CREG 015/2018 también regula el descuento cuando los activos NT1
    (transformador/red BT) son de la copropiedad**, no solo la clasificación
    de NT1: 50% de descuento en el cargo por uso si el usuario/copropiedad es
    dueño de UNO de los dos activos, 100% si es dueño de ambos — información
    directamente relevante para las preguntas sobre trafo `compartido` en
    edificios/conjuntos que ya maneja el bot (ver regla `trafo_uso` más
    abajo). También: 2 días hábiles para que el propietario avise si repone
    un activo NT1 en falla, si no el operador de red lo repone en 72 horas.
  - **"Frontera en falla" (CREG 038/2014, Art. 10 y Art. 35)**: si la
    calibración muestra que un medidor/TC/TP perdió su clase de exactitud, la
    frontera se declara en falla y aplica reliquidación — es la respuesta a
    "¿qué pasa si el medidor está mal calibrado o dañado?".
  - **Propiedad/mantenimiento del medidor (CREG 038/2014, Art. 5 y Art. 28)**:
    libertad para comprar el medidor en el mercado (no obligatorio comprarlo
    al operador de red) si cumple especificaciones técnicas; costos de
    mantenimiento a cargo del representante de la frontera y el usuario.
  - **FP capacitivo varía por nivel de tensión** (antes el prompt solo tenía
    el umbral genérico "también se penaliza"): ≥0,90 en niveles I/II, ≥0,95
    en nivel III, ≥0,98 en nivel IV.
- `_consulta_retie(update, ctx, texto)` mantiene hilo de conversación en
  `ctx.user_data["historial_retie"]` (mismo patrón que `historial_diagrama` /
  `_dialogo_diagrama`): cada pregunta se agrega con `{"role": "user"/"model",
  "text": ...}`, se recorta a `RETIE_HISTORIAL_MAX` entradas (ventana
  deslizante, ~4 intercambios) y se envía como conversación completa a
  Gemini vía `system_instruction=PROMPT_SISTEMA_RETIE` + `contents=conv`. El
  hilo se corta explícitamente (se pone `[] `) al entrar a otro flujo que no
  es una continuación de la consulta — `/menu` (ya limpia todo user_data),
  `/diagrama <texto>`, `cmd_clasificar`, y al activar `modo_diagrama_ia` —
  además de `/cancelar` (limpia todo). Si agregas un nuevo flujo que no es
  una consulta normativa, resetea `historial_retie` ahí también, o el bot
  arrastrará contexto de una consulta anterior sin relación.

## Modelo de configuración (cfg)
```
sistema : 'mono' | 'bifasico' | 'tri3h' (2 elem) | 'tri4h' (3 elem)   # sistema de la MEDIDA (no del trafo: ver trafo_tipo)
tipo    : 'directa' | 'semidirecta' | 'indirecta'
respaldo: bool                      # principal + chequeo (1 bloque, 2 medidores)
norma   : 'CENS' | 'RA8'
salida  : 'conexiones' | 'unifilar' | 'ambos'
rel_tc, rel_tp, tension, proyecto : str
conexion: 'simetrica' | 'asimetrica'   # solo medida directa
# instalacion / trafo:
instalacion: 'trafo' | 'barraje' | ''   # punto de conexion (unifilar)
trafo_uso: 'exclusivo' | 'compartido'   # ver regla de negocio abajo
trafo_n_usuarios: str      # cantidad de otros usuarios (solo si trafo_uso='compartido')
trafo_gabinete: bool|None  # True=gabinete/cuarto cerrado, False=red abierta, None=sin especificar
trafo_kva, trafo_tipo, trafo_kva_list, n_trafos, n_cc, n_tc, interruptor, v_mt, v_bt
# trafo_tipo ('monofasico'|'bifasico'|'trifasico') es la fase del TRANSFORMADOR y es INDEPENDIENTE de `sistema`
#   (la de la medida): un trafo trifasico puede alimentar una medida mono o bifasica; al reves no (ver gabinete).
# opcionales unifilar: dps (bool), rele (bool), rele_funcs (str ANSI)
# campos de acta (opcionales, ver "Unifilar de frontera"): transformadores [{kva,tipo,uso}],
#   configuracion_transformadores, planta_respaldo {existe,kva,transferencia}, ubicacion_medida, celda_medida {existe,tipo,estado}
```

### Subestación multi-celda (`tipo='indirecta'` + `n_trafos >= 2`)
Cuando la medida es indirecta y hay 2+ transformadores, `draw_unifilar_generico`
dibuja N **celdas de transformación INDEPENDIENTES** (`es_multi_celda`), no un
banco de monofásicos en paralelo: después del punto de medida MT (TC/TP +
bloque + medidor, sin cambios) se dibuja una **BARRA DE DISTRIBUCIÓN**
horizontal, y de ella cuelgan N ramas — cada una con su propio fusible/
seccionador, su propio transformador (`trafo_kva_list[i]`, tierra en ramal
lateral) y su propia carga (`TR1`, `TR2`, ... cada uno con su triángulo de
CARGA independiente). Esto reemplaza cómo se dibujaba antes `n_trafos>=2` en
indirecta (círculos monofásicos formando un solo trafo trifásico para una
sola carga) — decisión explícita del usuario tras preguntarle, porque son
topologías reales distintas (una subestación con celdas independientes vs.
un banco monofásico). El **banco monofásico en paralelo sigue existiendo sin
cambios para `semidirecta`/`directa`** (`n_trafos>=2` ahí sigue siendo 3
unidades formando UN trafo trifásico para UNA sola carga — no toques eso).
- `cell_w` acota el ancho total del abanico (`max(5, min(11, 35/(n-1)))`):
  con muchas celdas la barra puede llegar a rozar la etiqueta "MEDIDOR" del
  punto de medida (quedan casi al mismo nivel vertical) — si cambias esta
  geometría, vuelve a verificar ese caso con 5+ celdas.
- Todos los bloques posteriores que asumen UNA sola carga (protección
  después, seccionador después, sección CARGA final) se saltan con
  `and not es_multi_celda` / `if not es_multi_celda:` — si agregas algo
  nuevo ahí, agrégale el mismo guard o se dibujará encima del abanico.
- El flujo de menú (`kva_trafo_idx`/`kva_trafo_list` en `bot.py`) ya pregunta
  la capacidad de cada transformador por separado y llena `trafo_kva_list`
  — no necesitó cambios para soportar esto.

### Regla: trafo `exclusivo` vs `compartido`
Un trafo **compartido** (edificios, conjuntos residenciales) alimenta un
barraje BT del que se derivan VARIOS usuarios, cada uno con su propio medidor
DIRECTO — no hay un solo medidor semidirecta/indirecta para todos. Por eso:
- Si el usuario menciona "trafo compartido" / "varios usuarios" y NO dijo un
  tipo de medida explícito, `tipo` se fuerza a `'directa'` (parser.py y el
  prompt de diálogo IA aplican esta regla; el menú de botones ya solo ofrece
  esta pregunta cuando tiene sentido).
- Si es compartido, se pregunta ADEMÁS cuántos otros usuarios (`trafo_n_usuarios`)
  y si el punto de derivación está en gabinete/cuarto cerrado o en red abierta/poste
  (`trafo_gabinete`) — esto decide si el dibujo lo encierra o no.
- `draw_unifilar_generico` dibuja el trafo distinto según `trafo_uso`: si es
  `'compartido'`, agrega un BARRAJE BT explícito con la cantidad real de
  medidores adicionales ("+N medidores más en este punto", a la IZQUIERDA
  para no cruzarse nunca con la conexión propia de este usuario que sigue
  más abajo). Después del barraje se deja un espacio vertical explícito (no
  cosmético: evita que el TC/bloque/medidor de este usuario se solape con
  el barraje) y se marca "ESTE MEDIDOR" con una flecha apuntando al círculo
  del medidor mismo (nunca cerca del TC ni del trafo/barraje), para
  distinguirla de los demás medidores del punto compartido. Si `trafo_gabinete=True`,
  el recinto punteado ("GABINETE COMPARTIDO") se dibuja DESPUÉS de resolver
  la posición del medidor y encierra **barraje BT + TC/bloque/medidor de
  este usuario** — el gabinete de medidores compartido es donde están los
  medidores, NUNCA el transformador (que físicamente está afuera: en su
  propio poste o cámara). El transformador queda siempre por ENCIMA del
  borde superior del recinto (`gy1 = bt_y + 2`), fuera de la caja. Si es
  `'exclusivo'` (o `trafo_gabinete` no se especifica/`False`), no se dibuja
  nada de esto.
- Variables `bt_y`/`gabinete` se inicializan en `None`/`False` al principio
  de `draw_unifilar_generico` (antes de que `draw_medida_lateral` se
  defina) precisamente porque para `tipo='indirecta'` esa función se llama
  ANTES de que el bloque TRAFO fije esos valores — sin el default, referenciarlas
  ahí lanzaría `NameError`. Si tocas ese flujo, respeta el orden.
- Para tipo directa/semidirecta con `instalacion='trafo'` siempre se dibuja:
  una línea horizontal corta en "RED (M.T.)" (la MT es una derivación de un
  alimentador que sigue sirviendo otros puntos, no una acometida exclusiva
  en punta de línea), protección MT (pararrayos ZnO + cortacircuitos
  fusible) antes del trafo, y su puesta a tierra en un ramal lateral (no
  tapada por la línea principal). El conductor se etiqueta en ambos
  extremos (trafo/red → medidor, y medidor → carga), con placeholder
  `"cal. ?"` si no se especificó.
- Si agregas más elementos a la rama del trafo/barraje compartido, respeta
  el espacio reservado a la derecha del eje para el TC/bloque/medidor de
  ESTE usuario (draw_medida_lateral lo usa siempre) — cualquier anotación
  del punto compartido (otros medidores, gabinete, etc.) debe ir a la
  izquierda o con separación vertical explícita, nunca compartiendo x/y
  con esa zona.
- `_verificar_coherencia()` en `bot.py` asume `'exclusivo'` como default
  conservador si ningún flujo de entrada capturó `trafo_uso` (y `red abierta`
  si no se especificó `trafo_gabinete`), y avisa al usuario en el caption de
  la imagen que se hizo esa suposición.

## Migracion hibrida Gemini/Claude (Anthropic)
El usuario decidio migrar de Gemini a Claude, pero **solo parcialmente**:
`_consulta_retie` (consultas normativas RETIE/CREG) **se quedo en Gemini** a
proposito, porque el RAG (File Search Store, ver seccion "RAG" mas abajo) no
tiene equivalente directo en la API de Claude -- Anthropic no ofrece un
servicio de indexacion/busqueda gestionado como el de Gemini. Migrar tambien
esa funcion habria significado perder de un plumazo la precision normativa
que costo activar (RETIE completo + CREG indexados). Con el corpus actual
(~70 MB en 14 documentos) tampoco es viable meterlo directo en el contexto
de Claude de una sola vez.

`_dialogo_diagrama` (dialogo guiado para armar un diagrama) y
`_analizar_foto_cx` (analisis de fotos de conexiones) **si se migraron a
Claude** -- ninguna de las dos depende del RAG, solo del prompt del sistema
(+ vision en el caso de fotos), que Claude cubre igual de bien.

Detalles tecnicos de la migracion:
- Cliente: `_claude_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)`,
  mismo patron que `_genai_client` (`None` si no hay `ANTHROPIC_API_KEY`,
  cada funcion chequea esto primero y responde con un mensaje claro).
- Modelo: `CLAUDE_MODEL = "claude-sonnet-5"` (PDF); dialogo y foto usan Haiku 5.5 desde oct/2026 (ver "Costo, 2a pasada").
- `system_instruction` de Gemini → parametro `system=` de
  `client.messages.create()`. `contents=` → `messages=[{"role":"user",
  "content": ...}]`.
- Imagenes: en vez de `types.Part.from_bytes(...)`, un content block
  `{"type":"image","source":{"type":"base64","media_type":"image/jpeg",
  "data": base64_str}}` dentro del mismo mensaje que el texto del prompt.
- Extraer el texto de la respuesta: Gemini tenia `response.text` directo;
  Claude devuelve `response.content` como una LISTA de bloques (puede haber
  mas de un bloque de texto) -- se concatenan con
  `"".join(b.text for b in response.content if b.type == "text")`.
- **Thinking en Claude (CORREGIDO, oct/2026)**: antes este documento decia que
  Claude NO activa "thinking" por defecto. Eso es FALSO para `claude-sonnet-5`:
  corre con adaptive thinking por defecto, y esos tokens (a) se facturan como
  salida ($10/M) y (b) salen del MISMO `max_tokens` que la respuesta visible --
  el mismo riesgo que ya mordio a Gemini. Por eso `_dialogo_diagrama` manda
  `thinking=CLAUDE_DIALOGO_THINKING` (`{"type": "disabled"}`): es captura de
  datos con reglas claras en el prompt, no necesita razonar. **Solo vale para
  `claude-sonnet-5`**: en `claude-sonnet-5-5` `disabled` da 400 (alli se usa
  `{"type": "between_tools"}`), asi que si cambias `CLAUDE_MODEL` revisa esa
  constante. `_analizar_foto_cx` deja el thinking ACTIVO a proposito (validar
  un cableado si se beneficia). El reintento por `stop_reason == "max_tokens"`
  (con `CLAUDE_MAX_TOKENS`) y el aviso por respuesta vacia se conservan como red
  de seguridad. No se pudo verificar el comportamiento en vivo sin API key.
- **SDK `anthropic` 1.x (bug real, oct/2026)**: el usuario vio "Error con el
  servicio IA (TypeError)" en CADA intento de diagrama por IA. Causa:
  `client.messages.create()` en el SDK 1.x ya NO acepta `temperature`/`top_p`/
  `top_k` (`TypeError: unexpected keyword argument 'temperature'`), y el bot
  los pasaba en `_dialogo_diagrama` y `_analizar_foto_cx` -- el
  `except Exception` genérico lo convertia en ese mensaje sin pistas. Se
  quitaron. NO los vuelvas a agregar; el control de longitud/estilo va por el
  prompt y por `max_tokens`. (El `temperature=0.25` de Gemini en
  `_consulta_retie` es otra API y se queda.) `requirements.txt` ahora fija
  `anthropic>=1.0.0,<2` para que un salto de major no rompa el deploy sin
  aviso. El SDK 1.x usa `httpx2` (no `httpx`) internamente.
- **Los tests de Claude deben usar el SDK REAL**: el cliente simulado a mano
  que se uso en la migracion original aceptaba cualquier kwarg, por eso no
  detecto el `TypeError`. `test_claude_sdk.py` construye un
  `anthropic.AsyncAnthropic(api_key="sk-test", max_retries=0,
  http_client=<AsyncClient con MockTransport>)` -- la firma de
  `messages.create()` se valida de verdad. Cubre: ausencia de `temperature`,
  respuesta correcta, DIAGRAMA_LISTO -> genera y envia el unifilar,
  `max_tokens` -> reintento, respuesta vacia, 529 con reintento, 401 -> "Clave
  API", 404 -> "Modelo Claude no disponible" y el analisis de foto con bloque
  de imagen. Si agregas otra llamada a Claude, agrega su caso ahi.
- Reintentos: el SDK de Anthropic tiene EXCEPCIONES TIPADAS
  (`anthropic.OverloadedError`, `anthropic.RateLimitError`,
  `anthropic.InternalServerError`, `anthropic.APITimeoutError`,
  `anthropic.AuthenticationError`, `anthropic.NotFoundError`) -- a
  diferencia de Gemini, donde había que parsear el string del mensaje de
  error ("503" in msg, etc.) para saber si algo era reintentable. Si agregas
  un nuevo punto de llamada a Claude, usa `except (anthropic.X, anthropic.Y):`
  con las excepciones tipadas, NO vuelvas al patron de parsear texto.
- Mismo criterio de timeouts que Gemini: TODA llamada envuelta en
  `asyncio.wait_for(..., timeout=CLAUDE_TIMEOUT_S)` (= `GEMINI_TIMEOUT_S`,
  25s), con reintento en vez de rendirse al primer timeout (mismo
  razonamiento que la seccion de arriba sobre Gemini).
- Verificacion original con un cliente de Anthropic simulado a mano (OJO: ese
  tipo de simulacro NO valida la firma de `messages.create()` -- ver
  `test_claude_sdk.py` arriba para el test con el SDK real): respuesta
  exitosa con DIAGRAMA_LISTO, reintento tras un `OverloadedError` real (con
  un `httpx.Response`/`httpx.Request` de verdad -- OJO, construir estas
  excepciones a mano con `response=None` para un test truena con
  `AttributeError` porque `APIStatusError.__init__` si accede a atributos
  del response; hay que darle un `httpx.Response` real aunque sea de
  prueba), agotamiento de reintentos por timeout, y error de autenticacion
  en `_analizar_foto_cx`.
- `requirements.txt` gano `anthropic>=1.0.0,<2`; `render.yaml` gano la env var
  `ANTHROPIC_API_KEY` (junto a la ya existente `GEMINI_API_KEY`, que sigue
  siendo necesaria para `_consulta_retie` y el RAG).

### Costo de la API de Claude (oct/2026)
Precios Sonnet 5 (USD / 1M tokens): entrada $2, salida $10, lectura de cache
$0,20, escritura de cache (5 min) $2,50 (`CLAUDE_PRECIO` en `bot.py`; revisar si
cambia el modelo). **Estimacion** (sin API key no se pudo usar `count_tokens`;
tokens ±25 %): `PROMPT_DIAGRAMA` ~2.700 tokens, un dialogo de ~4 llamadas.
- Antes (sin cache, thinking por defecto): ~$0,03 a $0,07 por diagrama. Lo caro NO
  era la salida visible (~45 tokens/turno, el 14 %) sino (1) reenviar el prompt
  entero en cada turno (86 % del costo sin thinking) y (2) el razonamiento oculto.
  Pedir la salida "en JSON" casi no ahorra: ya es corta, y JSON usa MAS tokens.
- Ahora: `cache_control` ephemeral en el bloque `system` del dialogo (-70 %) y
  thinking apagado -> ~$0,008 por diagrama (~$0,014 con cache frio). Foto de
  conexiones ~$0,01 a $0,02. El menu y `parse_spec` NO llaman a la IA ($0).
- **El prompt debe ser byte a byte estable** (`PROMPT_DIAGRAMA` es constante;
  verificado). Una fecha, un id o un `.format()` dentro de el invalida el cache y
  el costo vuelve a ~4x sin que nada falle. El minimo cacheable de Sonnet 5 es
  1.024 tokens; el prompt de fotos (~560) NO llega, por eso no lleva cache.
- **Medir, no estimar**: `_log_uso_claude(tag, response)` escribe en el log
  `claude[dialogo|foto] in= cache_leido= cache_escrito= out= ~US$`. `out` incluye
  el thinking. Si `cache_leido` es 0 en turnos repetidos, algo invalida el cache.
- NO aplicado (el usuario eligio solo cache + thinking + log): una sola llamada que devuelva el
  JSON con `output_config.format` (~$0,003/diagrama, la mas barata) -- quita el
  dialogo pregunta por pregunta. Si se retoma: `parse_spec` primero (gratis) y
  llamar a la IA una vez solo si falta algo.
- `test_claude_sdk.py` cubre: cache_control, thinking apagado, conservarlos en el
  reintento, y el log de uso/costo.

### Costo, 2a pasada: modelo por ruta y filtrado de paginas (oct/2026)
Pedido: "hazlo mas barato". Se siguio `cost-optimize` (claude-api): tarifas de
https://platform.claude.com/docs/en/about-claude/pricing (consultada 7/oct/2026): Sonnet 5 $2/$10 por M
(entrada/salida), lectura de cache $0,20; **Haiku 5.5 $0,10/$0,50** (prompts <= 100K tokens; mas largos
$0,50/$2,50), lectura de cache $0,01, escritura 5 min $0,125. Sin API key ni eval no se pudo MEDIR la calidad:
los "free wins" (cache del dialogo, thinking apagado, topes, brevedad) ya estaban; lo que queda son
COMPROMISOS de calidad, y el usuario acepto solo estos (la IA no los aplica sola):
- **Dialogo y foto -> Haiku 5.5** (`CLAUDE_MODEL_DIALOGO`, `CLAUDE_MODEL_FOTO`; env var con el mismo nombre para
  cambiarlos en Render sin deploy, p. ej. `CLAUDE_MODEL_FOTO=claude-sonnet-5` si da por bueno un cableado
  incorrecto). Estimado por diagrama: dialogo ~US$0,0007 (antes ~0,008-0,013), foto ~US$0,0007 (antes ~0,015),
  ~-95 %. El PDF sigue en Sonnet 5 (`CLAUDE_MODEL_PDF`). Riesgo asumido: preguntas menos finas / dato mal llenado
  en el dialogo (el usuario lo ve en el caption y corrige con /ultimo -> Editar) y peor juicio visual en la foto.
  Detalles de Haiku 5.5: `thinking {"type":"disabled"}` vale con effort <= high (el default es `medium`);
  `_thinking_apagado(modelo)` da `between_tools` en claude-sonnet-5-5 (alli `disabled` es 400); piensa por
  defecto y ese razonamiento sale del MISMO `max_tokens` -> `CLAUDE_FOTO_MAX_TOKENS=4096` (es un tope, no un
  gasto); NO acepta `temperature`/`top_p`/`top_k` ni prefill ni `fallbacks` (no se usan); un `stop_reason ==
  "refusal"` llega como respuesta vacia y cae en el mensaje "No pude generar una respuesta".
- **PDF > 12 paginas con capa de texto -> solo las paginas de la medida** (`_filtrar_paginas_pdf`, `pypdf` en
  requirements.txt): se queda con las que mencionan medidor/contador/transformador/trafo/kVA/frontera/celda/
  bloque de pruebas/unifilar/acta (o 2 terminos debiles: TC, TP, medida, acometida, barraje, fusible,
  seccionador, planta) + la portada + las vecinas (+-1), y AVISA "leí solo las N (págs. 1, 14-17)". Va completo
  si: <= 12 paginas, escaneado (< 60 % de paginas con texto), cifrado, ninguna coincidencia, ahorro < 20 %,
  `pypdf` ausente o cualquier error, o el comentario dice "completo". Corre en `run_in_executor` (CPU) con tope
  de 25 s. Riesgo asumido: omitir una pagina sin esas palabras (por eso el aviso y la palabra "completo").
- `CLAUDE_PDF_EFFORT` (low|medium|high|xhigh|max; vacio = no se envia) existe pero NO se activo: recortar el
  razonamiento del PDF no fue aceptado. Mas palancas NO aplicadas: Haiku en el PDF (-95 %, riesgo en planos
  densos: probar antes con 2-3 PDF reales), recortar `PROMPT_DIAGRAMA` (~2.900 tokens, -10 % del dialogo,
  requiere eval), cachear el sistema del PDF (no se amortiza: pocos PDF por cada 5 min).
- `_log_uso_claude` ahora escribe el MODELO y estima con la tarifa del que respondio (`CLAUDE_PRECIOS`): si cambias
  de modelo, agrega su fila ahi. **Mide, no estimes**: pide a Render el log `claude[dialogo|foto|pdf] <modelo> in=
  cache_leido= cache_escrito= out= ~US$` tras unos dias.
- `test_claude_sdk.py` (modelo/thinking por ruta, tarifa por modelo, tope de la foto) y `test_pdf.py` (9 casos del
  filtro con PDF reales: filtra, avisa, no filtra chicos/escaneados/"completo"/danados).

### PDF -> unifilar (oct/2026)
Pedido: "con solo enviarle un PDF puedas leerlo y sacar el unifilar". `on_document`
(registrado con `filters.Document.ALL`) recibe el PDF y `_procesar_pdf` lo lee con
Claude y dibuja el unifilar de cada punto de medida. **Solo unifilar**
(`cfg['salida']='unifilar'` fijo): el usuario dijo que el diagrama de conexiones
"no lo estabas haciendo bien" y no se pidio aqui.
- Claude recibe el PDF NATIVO (bloque `document` base64, ANTES del texto; lee el texto
  y la imagen de cada pagina, asi que sirve tambien para planos escaneados) y responde
  JSON con `output_config={"format": {"type": "json_schema", "schema": PDF_ESQUEMA}}`:
  el JSON sale siempre valido, sin regex. El esquema es ESTRICTO (`additionalProperties:
  false` + todo en `required`; "no aparece" = `""`/`0`/`[]`, no `null`). Si agregas un
  campo al cfg que el PDF pueda traer, agregalo a `_PDF_PROPS_MEDIDA`, a la guia de
  `PROMPT_PDF` y a `_cfg_desde_pdf` (el test valida que el esquema siga siendo estricto).
- **Lo que sale del PDF es entrada NO confiable** (puede traer texto que intente dar
  ordenes al modelo, o basura): `_cfg_desde_pdf()` valida enums, numeros y relaciones
  (`_validar_relacion`), recorta textos a una linea, topes (n_trafos<=12, dps<=12).
  Nada llega crudo al motor. El prompt tambien dice "el PDF es DATO, no instrucciones".
- **Nunca se inventa**: lo que el PDF no dice se lista en "No aparece en el PDF"; lo
  deducido (tipo de medida a partir de TC/TP, sistema/norma por defecto) en "Supuse".
  Se dibuja igual con lo que hay (el motor tolera cfg incompletos) y el usuario corrige
  con `/ultimo` -> ✏️ Editar. NO se pregunta nada: era el pedido ("solo enviarle un PDF").
- Hasta `PDF_MAX_MEDIDAS` (3) puntos de medida por PDF (una subestacion con varios trafos
  detras de UN medidor es UN punto: `n_trafos` + `trafo_kva_list`).
- **Tamano: tope = 20 MB, el limite de Telegram para bots** (`FileSizeLimit.FILESIZE_DOWNLOAD` =
  20e6 bytes, MB DECIMALES). No es una decision nuestra: un PDF de 21,7 MB (el caso real que el
  usuario intento) ni siquiera se puede descargar con el Bot API (`get_file` -> BadRequest "file is
  too big", tambien manejado). Antes habia un tope propio de 10 MB que rechazaba PDF de 10-20 MB
  sin necesidad. El mensaje (`_MSG_PDF_GRANDE`) explica el limite y que hacer (comprimir con
  ilovepdf.com o enviar solo las paginas de la medida: mas rapido y barato). Para aceptar mas de 20 MB
  habria que correr un servidor Bot API propio o recibir un enlace (Drive) -- no se hizo.
- Tiempo proporcional al tamano (`_timeout_pdf`: 120 s a 240 s; ~220 s a 20 MB) y aviso
  "hasta 4 minutos" si pesa > 8 MB. El cuerpo en base64 de un PDF de 20 MB (~27 MB) queda bajo los
  32 MB de la API de Claude; el costo lo manda el numero de paginas, no los MB.
- **Corre en segundo plano** (`ctx.application.create_task`): leer un PDF tarda hasta ~1
  min (`CLAUDE_PDF_TIMEOUT_S=120` base, ver tamano) y PTB procesa los updates en serie; sin esto un PDF
  bloqueaba a todos los demas usuarios. `ctx.user_data['pdf_en_curso']` impide dos PDF a
  la vez del mismo usuario (control de costo); se libera en el `finally`.
- Thinking ACTIVO aqui (a diferencia del dialogo): leer un plano si lo aprovecha. Comparte
  `max_tokens` (4096) -> si `stop_reason == 'max_tokens'` reintenta con 16000. Costo: lo
  manda el numero de paginas (~1.500-3.000 tokens por pagina a $2/M) -> un PDF de 10
  paginas ~ $0,03-0,06; se registra con `_log_uso_claude("pdf", ...)`.
- Campos de acta (transformadores, planta, celda, ubicacion): ver "Unifilar de frontera" mas abajo.
- `test_pdf.py` (54 comprobaciones, SDK real + `MockTransport`, PDF real generado con
  matplotlib): peticion (bloque document, json_schema, caption), valores hostiles, varios
  puntos, faltantes, errores 400/401/404/529, max_tokens, segundo plano, candado.
- No verificado en vivo (sin API key): que el modelo extraiga bien de PDFs reales, y que la
  API acepte `output_config` + thinking + documento juntos. Probar con un PDF de verdad
  tras el deploy; si da 400 por el esquema, el mensaje cae en "No pude leer ese PDF".

### Brevedad en `_dialogo_diagrama` (feedback tras la migracion a Claude)
El usuario reporto que las respuestas del dialogo de diagramas quedaron
largas tras pasar a Claude -- Claude (incluso Sonnet) tiende a ser mas
verboso por defecto que `gemini-2.5-flash` (mas cortesias, mas contexto
explicado, aunque el prompt ya decia "preguntas breves"). Dos cambios,
NINGUNO por si solo era suficiente:
1. Nueva seccion `=== BREVEDAD (OBLIGATORIO) ===` en `PROMPT_DIAGRAMA`,
   ANTES de `IDIOMA` y `REGLAS ESTRICTAS`: maximo 1-2 lineas por respuesta,
   nada de "Perfecto"/"Entendido", no repetir lo que el usuario ya dijo, sin
   encabezados ni vinetas -- texto plano corrido como un chat real.
2. `CLAUDE_DIALOGO_MAX_TOKENS = 500` (bastante menor que
   `CLAUDE_MAX_TOKENS` = 1400): un limite de instrucciones en el prompt solo
   no es un limite duro -- un modelo puede irlo ignorando a medida que
   crece el historial de la conversacion. Un `max_tokens` mas chico SI es un
   limite duro a nivel de API. Solo se aplica a `_dialogo_diagrama` -- NO a
   `_analizar_foto_cx`, que necesita el presupuesto completo porque emite un
   reporte con varias secciones fijas (`PROMPT_VALIDACION_CX` ya tiene un
   formato de salida estructurado y acotado, no corria el mismo riesgo de
   alargarse). 500 da margen de sobra para el caso mas largo real (el bloque
   JSON de `DIAGRAMA_LISTO`, ~150-200 tokens) sin dejar espacio para que una
   pregunta simple se convierta en un parrafo.
Si notas que las respuestas se siguen alargando (o si el limite de tokens
alguna vez corta a medias el JSON de `DIAGRAMA_LISTO`, seria una señal de
que 500 quedo corto), ajusta primero el prompt y verifica con una
conversacion real antes de subir el limite -- subir el limite sin tocar el
prompt es la salida facil que reintroduce el problema original.

## Rediseño visual: medidor "premium", bloque de prueba, plano de simbologia sincronizado
Feedback directo del usuario tras ver los primeros renders del "Prompt
Maestro": el medidor se veia poco cuidado, el bloque de pruebas en
semidirecta quedaba casi del mismo tamano que el medidor (se veian como
"gemelos"), y el plano de simbologia (panel derecho) tenia iconos
DESACTUALIZADOS que ya no coincidian con lo que realmente se dibuja en el
cuerpo del diagrama -- una caja azul redondeada para "Bloque de prueba" y
una caja oscura solida para "Medidor de energia", ambos de una version
anterior al rediseño IEC de este mismo proyecto (circulo+kWh, rectangulo
blanco). Cambios:
- **`_u_meter(ax, x, y, r=8.0, fontsize=8, lw=1.8, label_below=None,
  label_fontsize=6.3)`** y **`_u_bloque_prueba(ax, x0, y0, w, h, linea1="",
  linea2="")`** (nuevas, junto a los demas `_u_*` cerca del inicio del
  archivo): son las UNICAS funciones que dibujan estos dos simbolos, tanto
  en el cuerpo del diagrama (`draw_medida_lateral`, el bloque DIRECTA
  inline) como en el plano de simbologia (`sym_items` dentro de
  `draw_unifilar_generico`). **Regla dura**: si tocas la forma de estos dos
  simbolos, hazlo SOLO editando estas dos funciones -- nunca dupliques el
  dibujo inline en otro lugar, o el plano de simbologia se vuelve a
  desincronizar del cuerpo (que es exactamente el bug que se acaba de
  corregir).
- Medidor: circulo doble (anillo exterior + interior mas fino) en vez de un
  circulo simple -- sigue siendo flat/vector, sin degradados ni sombras
  (Convenciones fijas se mantienen), pero se ve mas "cuidado"/premium sin
  dejar de leerse como simbolo de instrumento de precision real.
- Radio del medidor ahora es FIJO (r=8 medidor unico, r=6 en par
  PRINCIPAL+RESPALDO), YA NO se deriva de `bq_h` (altura del bloque de
  pruebas) -- antes, en semidirecta (`bq_h=12`, sin TP), la formula
  `r=min(9,max(6,bq_h/2))` daba r=6, exactamente la mitad de la altura del
  bloque, por lo que ambos quedaban con la misma altura visual. `bq_h` para
  el caso sin TP tambien se redujo (12→9, 22→18): el bloque de pruebas real
  es mas chico/discreto que el medidor, que es el elemento protagonico.
- TP ahora se dibuja con `ground=True` (antes `False`): el transformador de
  tension "cierra su circuito" a tierra en vez de quedar como un instrumento
  flotante sin referencia -- aplica en `draw_medida_lateral` y en el plano
  de simbologia.
- Seccionador del unifilar para `tipo='indirecta'`: la posicion "antes" (que
  ya existia en el codigo, antes del transformador de potencia -- no
  confundir con "transformador de potencial/TP") es la recomendada quando
  el objetivo es poder aislar el transformador para mantenimiento; "despues"
  sigue existiendo para el caso de aislar la CARGA sin desenergizar el
  transformador. Ninguna de las dos se elimino, pero al armar ejemplos/demos
  usa "antes" como el caso tipico salvo que el usuario pida lo contrario.
- Recordatorio reforzado (ya estaba en Convenciones fijas, el usuario lo
  repitio explicitamente): NUNCA agregues un seccionador junto a un
  cortacircuito "porque se ve mas completo" -- el cortacircuito YA sirve
  para seccionar en vacio. Solo se dibuja seccionador cuando el cfg lo trae
  explicitamente (`seccionador='antes'|'despues'`), nunca por defecto.

## Campos del "Prompt Maestro" (circuito, v_mt general, DPS banco, tendido, interruptor detalle)
El usuario paso un documento de especificacion ("Prompt Maestro para Diagramas
Unifilares") con un cuestionario y reglas de estetica adicionales. Comparado
contra lo ya implementado: tipo de medida, seccionador antes/despues (solo
indirecta... en realidad solo cuando instalacion=trafo, ver seccion de
arriba), trafo compartido con N usuarios y gabinete/red abierta, subestacion
multi-celda -- todo eso YA estaba. Lo que se agrego nuevo:
- **`circuito`** (string libre, ej. "Magdalena"): rotulo informativo, se
  muestra como "Circuito: X" justo debajo del titulo del unifilar. Parser.py
  lo detecta con `circuito|cto` + un solo token (ver por que un solo token:
  evitar que capture de mas en una frase larga). No afecta nada del dibujo,
  es solo identificacion del plano.
- **`v_mt` ya no es exclusivo de indirecta**: ahora tambien aplica a
  directa/semidirecta con `instalacion='trafo'` (hay un tramo MT real ahi,
  de RED al trafo, aunque el tipo de medida sea BT) -- el label "RED (M.T.)"
  usa `cfg.get('v_mt')` si esta presente. `_verificar_coherencia()` cambio su
  guard: antes descartaba v_mt para CUALQUIER directa/semidirecta; ahora solo
  lo descarta si ADEMAS `instalacion != 'trafo'` (sin trafo no hay tramo MT
  que rotular).
- **`dps_cantidad`** (entero, default 1): pararrayos ZnO dibujados en banco
  de N en vez de uno solo. Implementado en los DOS lugares donde se dibuja
  pararrayos (entrada indirecta, y proteccion MT del trafo en directa/
  semidirecta) -- **pero con una diferencia importante entre ambos**: en el
  bloque TRAFO (directa/semidirecta) SI se dibujan los N iconos en fila,
  porque ahi hay espacio; en la entrada de INDIRECTA NO se dibujan N iconos
  -- el espacio entre el eje y el bloque TC/TP (`bq_x0 = xc+20` en
  `draw_medida_lateral`) es demasiado angosto (un solo pararrayos en
  `arrx=xc+18` ya esta al limite) y con 2+ iconos se encima con el TP/bloque.
  Ahi se dibuja SIEMPRE un solo icono y se anota "(banco de N)" solo en el
  texto. Si vas a tocar esta geometria, vuelve a probar con dps_cantidad>=2
  en indirecta específicamente, es el caso que se rompe primero.
- **`tendido`** ('aereo' default | 'subterraneo'): el primer tramo de
  conductor (RED -> primer elemento de proteccion) se dibuja punteado
  cuando es subterraneo, con etiqueta "subterráneo" al lado (`cable_lbl`).
  Importante: el patron de rayas tiene que ser FINO (`(0, (1.5, 1.2))`), no
  el mismo que se usa para el neutro en otros lados (`(0,(6,3))` o similar,
  mas grueso) -- ese tramo mide solo ~5 unidades de dibujo, y con un patron
  de rayas grande (probado con `(0,(4,2))`) se ve visualmente SOLIDO porque
  no alcanza ni un ciclo completo de raya+espacio. Verificado con un test
  aislado de matplotlib variando el patron antes de aplicarlo — si cambias
  este patron, vuelve a probarlo aislado con un segmento corto (~5 unidades)
  antes de asumir que "cualquier tupla de dash se ve punteada".
- **Seccionador con cuchilla de puesta a tierra integrada**: `_u_disc()` gano
  un parametro `tierra=False` que dibuja un ramal lateral verde a tierra
  junto al seccionador. Los DOS puntos donde se dibuja el seccionador del
  unifilar (antes/despues de la medida, en `instalacion=trafo`) ahora
  siempre pasan `tierra=True` -- es una caracteristica fija del "seccionador
  unico" de la jerarquia, no algo que el usuario configura. (El seccionador
  pequeño de la bornera en el diagrama de CONEXIONES, `_draw_semi_indirecta_retie`,
  NO se toco -- ahi son 3 iconos por fase a escala chica, ponerles tierra
  individual se veria mal.)
- **`interruptor_polos`/`interruptor_tipo`**: se agregan al mismo texto de
  "Proteccion" (`draw_prot()` gano parametros `polos`/`tipo`), ej.
  "200 A  3P  termomagnetico" en una sola etiqueta. No son campos nuevos
  independientes en el dibujo, solo enriquecen el texto que ya existia.
- Todos estos campos se agregaron a `PROMPT_DIAGRAMA` (dialogo IA) con la
  regla explicita de "pregunta SOLO si el usuario ya lo menciono" para
  `dps_cantidad`/`tendido`/`circuito`/`interruptor_polos`/`interruptor_tipo`
  -- son datos opcionales de refinamiento, no queremos que el dialogo se
  alargue preguntando cosas que el 90% de los usuarios no necesita. Tambien
  se agregaron a `parser.py` (texto libre, regex simples) para los que se
  prestan a eso (`circuito`, `dps_cantidad`, `tendido`, `v_mt` como "N kv").
  NO se agregaron preguntas nuevas al menu de botones (`on_button`) -- si se
  quiere eso despues, es un cambio de alcance mayor (tocar el state machine
  lineal), se dejo fuera deliberadamente de esta pasada.

## QA de sept/2026: bugs encontrados por revision de codigo (no reportados por el usuario)
- **Seccionador "despues de la medida" no se dibujaba para `tipo='indirecta'`**:
  `diagram_engine.py` tenia `elif seccionador_pos == "despues" and tipo !=
  "indirecta":` — pero el menu de botones SOLO ofrece la pregunta "antes/despues"
  cuando `tipo=='indirecta'` (para semidirecta va directo a la pregunta de TC,
  para directa no se pregunta). Resultado: la opcion "Despues de la medida" en
  el UNICO tipo donde se ofrece, no dibujaba nada — la pantalla de confirmacion
  seguia diciendo "Seccionador despues de la medida" pero el PNG no tenia el
  simbolo. Se quito la exclusion `and tipo != "indirecta"`; verificado con
  render (indirecta + trafo exclusivo + seccionador=despues ya muestra el
  simbolo entre el trafo y la carga).
- **`trafo_uso='compartido'` + subestacion multi-celda (`n_trafos>=2` en
  indirecta) es una combinacion sin sentido que igual era alcanzable via el
  menu de botones** (el menu pregunta `trafo_uso` sin importar `tipo`, a
  diferencia de `parser.py`/el dialogo IA que si fuerzan `tipo='directa'`
  cuando se menciona compartido). El renderer ya ignoraba el bloque de
  barraje/gabinete compartido en este caso (`es_multi_celda` salta ese
  bloque), pero dejaba la anotacion "ESTE MEDIDOR" en el punto de medida MT de
  la subestacion sin motivo (esa anotacion existe para distinguir el medidor
  propio entre varios en un punto compartido real). `_verificar_coherencia()`
  ahora fuerza `trafo_uso='exclusivo'` cuando detecta esta combinacion, con
  aviso al usuario en el caption — igual que ya hacia con el default de
  `trafo_uso` sin especificar.
- **Los 6 hallazgos restantes ya se corrigieron tambien** (QA de continuacion,
  mismo dia):
  - `proteccion_pos` (antes_tc/despues_tc/ambos_tc/despues_medidor, usado
    antes solo para el texto resumen del menu) ahora se traduce a
    `proteccion_antes`/`proteccion_despues` dentro de `_verificar_coherencia()`
    -- antes, "Antes del TC" y "Ambos lados" se dibujaban igual que "Despues
    del TC" porque `diagram_engine.py` nunca leia `proteccion_pos`. Verificado
    con render: semidirecta + "antes del TC" ahora si dibuja la proteccion
    antes del TC.
  - `instalacion=""` (documentado como "red sin trafo") ya NO se coacciona a
    `"barraje"`. Tiene su propio render minimo: solo "RED (B.T.)" sin simbolo
    de barra, para la acometida mas simple (sin trafo, sin barraje explicito).
    Esto afectaba a CUALQUIER especificacion de texto libre sin mencion de
    transformador (el caso mas comun de todos, p.ej. "monofasica directa")
    -- antes salia rotulada "BARRAJE B.T." sin que el usuario dijera nada de
    un barraje. Verificado con render.
  - `seccionador='antes'`/`'despues'` en el JSON de la IA: `PROMPT_DIAGRAMA`
    ahora aclara que SOLO tiene efecto si `instalacion='trafo'` (es el
    seccionador de MT junto al transformador) y corrige la descripcion que
    tenia antes ("antes/despues del bloque de pruebas" no es lo que dibuja
    el codigo -- es antes/despues del trafo, lado red vs. lado carga).
  - `dps`/`rele`/`rele_funcs`: se quito su deteccion en `parser.py` (texto
    libre) porque no tenian ningun efecto real -- solo los leia `draw()`
    (legacy, ya eliminada). `draw_unifilar_generico()` dibuja pararrayos ZnO +
    cortacircuitos SIEMPRE que hay trafo, sin flag opcional (ver "[x] DPS" en
    Estado/pendientes abajo), asi que la deteccion de texto libre solo podia
    confundir (un usuario escribiendo "sin pararrayos" los veia igual).
  - Se eliminaron `draw()`, `draw_unifilar()`, `draw_unifilar_trafo()` y
    `_u_meter()` de `diagram_engine.py` (~450 lineas muertas, marcadas
    "OBSOLETO" en el propio codigo) y `test_bot_local.py` (test ya roto que
    las usaba, ademas llamaba `_procesar_texto()` con la firma vieja de 2
    argumentos).
  - Campos vestigiales `trafo_presente`, `interruptor_pos`,
    `interruptor_antes_kva`, `interruptor_despues_kva` eliminados de
    `parser.DEFAULT` (nunca se leian en ningun lado); `test_parser_fields.py`
    actualizado para imprimir `instalacion`/`interruptor` (los campos reales)
    en vez de esos.

## QA de oct/2026: menú "Indirecta + Cx + Uni" no generaba nada
Reporte: "el unifilar no me está generando diagrama". El motor
(`draw_unifilar_generico`) NO era el problema (sin fallos en ~1000 cfgs
sintéticos). Causa real, en `bot.py`: el commit `c8ce231` pasó `n_trafos` de
botones a TEXTO LIBRE (`esperando_n_trafos`) y borró el handler
`campo == "n_trafos"`, pero dejó 2 pantallas (`sistema` y `subtipo`, solo
alcanzables con tipo=indirecta y salida="ambos") mostrando los botones viejos
`n_trafos:1..4` -> al tocarlos el bot no respondía y nunca llegaba a generar.
Arreglo: ambas pantallas ahora piden el número por texto, igual que las demás.
**Regla**: si cambias una pantalla de botones a texto (o viceversa), busca TODAS
las que emiten ese callback (`grep '"n_trafos"'`) y corre `test_menu_walk.py`.
- (Corregido después, ver "Pendientes resueltos" abajo): con salida "unifilar"
  sola el menú no preguntaba `sistema`; ahora sí, siempre.

## Seccionador, cuadro de datos y rótulos de secundarios (oct/2026)
Pedido del usuario, tomando como ejemplo un script externo de unifilar
indirecta (700 kVA, TC 30/5, TP 13200/120, "seccionador tripolar 13,2 kV
después de la medida"). Se conservó el motor IEC con protecciones y bloque de
prueba (el ejemplo omitía CC fusibles, pararrayos y bloque de prueba, que aquí
son obligatorios) y se adoptó de él lo siguiente:
- **El seccionador se describe SIEMPRE respecto al TRAFO**, no a la medida:
  `'antes'` = entre el punto de medida y el trafo (lado MT, rótulo "Seccionador
  MT 13.2 kV"); `'despues'` = aguas abajo del trafo (lado BT, "Seccionador BT").
  Antes el menú preguntaba "antes/después de la medida", que en indirecta (medida
  en MT, aguas arriba del trafo) significaba lo CONTRARIO de lo dibujado. Todo
  texto visible sale de `_SECC_TXT/_SECC_CORTO/_SECC_BOTONES/_SECC_PREGUNTA`
  (bot.py) -- no escribas literales nuevos. Los valores del cfg no cambiaron.
- `parser.py` ahora reconoce "seccionador": posición explícita (antes/después
  del trafo, lado MT/BT) o relativa a la medida ("después de la medida" ->
  `'antes'` en indirecta, `'despues'` en semi/directa); mencionado sin posición
  -> `'antes'`; "sin seccionador" -> nada. `test_seccionador.py` lo cubre.
- `_verificar_coherencia()` avisa (ya no descarta en silencio) cuando el
  seccionador "antes" no tiene trafo, y cuando una subestación multi-celda
  (n_trafos>=2 en indirecta) no dibuja seccionador/protección generales.
- **Cuadro de datos** (columna derecha, sobre el plano de simbología): lista
  SOLO lo que realmente queda dibujado (p.ej. no lista el seccionador en
  multi-celda). Sus filas se arman ANTES de crear la figura porque su altura
  decide `H` (el lienzo crece lo necesario; la figura crece en proporción
  `11*H/115` para que la escala de símbolos/texto no cambie). Si agregas un
  elemento nuevo al unifilar, agrégalo también a `filas` o el cuadro mentirá.
- Rótulos "sec. 5 A" / "sec. 120 V" sobre el hilo TC/TP -> bloque (derivados
  de `rel_tc`/`rel_tp`), alineados a la derecha pegados al bloque.
- Arreglos de dibujo encontrados al "energizar":
  1. la línea principal atravesaba el símbolo del seccionador (se leía como
     puenteado/cerrado): ahora llega solo a los contactos;
  2. hueco de 1 unidad entre el trafo y el siguiente elemento (circuito
     abierto en el dibujo);
  3. el seccionador tocaba el círculo del trafo / el triángulo de CARGA;
  4. "(paralelo) TP ..." se encimaba con el pararrayos de indirecta;
  5. el rótulo del conductor ("cal. ?") tocaba el trafo / quedaba sobre el
     rótulo de la protección: ahora tiene su propio tramo;
  6. trafo compartido: el recinto del gabinete CRUZABA el círculo del trafo
     (contra el invariante documentado): el barraje compartido se separó 4 u
     del trafo (`bt_y = trafo_y - 9`, el recinto llega hasta `bt_y + 2`).
### Pendientes resueltos (oct/2026, segunda pasada)
- **Menú**: `salida` ya no se salta la pregunta de `sistema` con "solo unifilar"
  (el handler de `sistema` decide el siguiente paso). `test_menu_walk.py` falla si
  un camino de solo-unifilar genera sin pasar por `sistema:*`. No se deriva
  `trafo_tipo` del sistema a propósito: un usuario monofásico puede colgar de un
  trafo trifásico compartido.
- **Parser**: el nombre de un circuito / punto de conexión ("circuito RA8",
  "cto: RA8", "punto de conexión RA8") se quita del texto antes de buscar la
  norma; "CENS RA8" suelto sigue lanzando "Norma ambigua".
- **Medida directa en línea**: el medidor arrancaba por encima de `y` (se
  encimaba con la protección). Ahora `y_mid = y - 2 - r` (y en respaldo el nodo
  de derivación está 2 u bajo `y`); bajo el círculo hay 5 u de conductor antes de
  la CARGA. Los rótulos MEDIDOR/PRINCIPAL/RESPALDO van al costado de su
  conductor (`_u_meter(..., label_dx, label_ha)`), no encima: antes los
  tachaba la línea. La barra de unión del respaldo bajó para no cruzar los rótulos.
- **Multi-celda**: el rótulo "TRi kVA" va a la derecha de su rama (antes lo
  tachaba la línea); con celdas muy juntas (`cell_w < 8`) se parte en tres
  líneas ("TRi / 500 / kVA"). Verificado con 3, 6 y 8 celdas.
- Hueco de 1 u entre el barraje compartido y la derivación a los medidores.
- Renderer detallado, indirecta: faltaba el conductor desde el nodo del TC hasta el
  seccionador/trafo/barra (~3 u de circuito abierto bajo el TC): `vline(tc_y, tc_y - 3)`.

## Unifilar de medida INDIRECTA en estilo "plano limpio" v2 (oct/2026)
Pedido explícito del usuario ("hazlo como el ejemplo, tal cual") y luego
("critica esta versión, detecta 3 debilidades y crea una mejor"). `draw_unifilar_generico`
despacha a **`draw_unifilar_indirecta_pro(cfg, out)`** cuando `tipo='indirecta'`,
`n_trafos < 2` y `cfg.get('estilo') != 'detallado'`. Layout vertical del ejemplo:
barra de RED -> [pararrayos + CC fusibles] -> TC -> derivación TP (derecha, a
tierra) -> [seccionador] -> trafo -> flecha "A CARGA"; medidor a la izquierda con
sus secundarios punteados pasando por el **BLOQUE DE PRUEBAS**; cuadro de datos al
pie. Sin el cuadro "RA8" (el usuario lo pidió quitar): la barra baja directo a
las protecciones/TC; `circuito` va en el cuadro de datos.

Las 3 debilidades de la v1 (y su arreglo en v2):
1. **Circuito no energizable / incompleto.** La v1 dibujaba el seccionador ABIERTO
   (la línea se cortaba en los contactos -> el único camino a la carga quedaba
   abierto; ese corte lo introduje yo al "arreglar" que la línea atravesara el
   símbolo) y había perdido neutro del trafo a tierra, Dyn11, CC fusibles y
   pararrayos. v2: seccionador **cerrado por defecto** y rotulado "(cerrado)"
   (`cfg['seccionador_estado']='abierto'` lo abre: línea cortada + "(ABIERTO)");
   neutro del secundario a tierra + "Dyn11" (solo trifásico); "N CC fusibles MT" y
   pararrayos ZnO (`dps_cantidad` -> "banco de N", un solo icono) en la entrada.
2. **Símbolos ambiguos y secundarios incorrectos.** TC, TP y trafo usaban el mismo
   par de círculos y los secundarios iban directo al medidor. v2: TC = anillo ROJO
   sobre el conductor, TP = par AZUL pequeño a tierra, trafo = par grande NEGRO;
   cada secundario punteado toma el color de su transformador; ambos pasan por el
   bloque de pruebas con "secundarios a tierra". Texto de referencia del repo
   (`retie_docs/creg_calidad_servicio_energia.txt`): bloque de pruebas "obligatorio
   en medida semidirecta e indirecta"; (`subestaciones_transformadores_distribucion.txt`)
   pararrayos ZnO en entradas MT y neutro del trafo a la malla de tierra.
3. **Números sin validar.** La v1 dibujaba TC 30/5 para 700 kVA a 13,2 kV (In =
   30,6 A = 102 % del primario) sin avisar. v2: `_validar_indirecta(cfg)` ->
   `[(nivel, corto, largo)]`: In = kVA/(√3·kV) (mono/bif: kVA/kV) vs primario del
   TC (>120 % err, 100-120 % warn "justo", <20 % warn "sobredimensionado", resto
   ok) y primario del TP vs red (L-L o L-N). Si no hay `v_mt`, el kV se deduce
   del TP (trifásico: L-L, o L-N si ×√3 coincide con una tensión normalizada;
   mono/bifásico: tal cual) y se marca "[kV est. del TP]". Son criterios de
   DISEÑO, no una cita normativa. Salen en el cuadro (✓/⚠/✗) y `_verificar_coherencia`
   agrega al caption solo lo que NO está ok. `_enviar_foto` recorta el caption a
   1024 caracteres (límite de Telegram: si se pasa, la foto no se entrega).
- Todo el texto dibujado usa coma decimal (`_es()`): "13,2 kV", "30,6 A".
- Seccionador: `'antes'` = entre la medida y el trafo (lado MT); `'despues'` = tras
  el trafo/protección (lado BT). Protección (`proteccion_despues` o `interruptor`) =
  cuadrito bajo el trafo. `proteccion_antes` no se dibuja en indirecta. Respaldo =
  dos medidores lado a lado. El lienzo crece con el contenido; 1 unidad = 1 pulgada.
- Siguen en `draw_unifilar_generico`: directa, semidirecta, multi-celda e indirecta
  con `cfg['estilo']='detallado'` (con plano de simbología).
- **En el menú** (pantalla de confirmación, NO en el flujo lineal de preguntas): fila
  `Estilo` + botones de un toque `🎨 Estilo: Limpio ⇄` y `🔀 Seccionador: cerrado ⇄`
  (callbacks `editval:estilo:<v>` / `editval:seccionador_estado:<v>`, reusan el handler
  de edición) y los mismos campos en ✏️ Editar. `_aplica_estilo(cfg)`: solo indirecta +
  unifilar/ambos + un trafo. Valores del cfg: `estilo` 'limpio'|'detallado',
  `seccionador_estado` 'cerrado'|'abierto' (default cerrado en AMBOS renderers; abierto
  corta el conductor, dice "ABIERTO" y `_verificar_coherencia` avisa que el diagrama
  muestra la instalación desenergizada). También en el parser ("seccionador abierto",
  "detallado"/"plano de simbología") y en el prompt de la IA (omitir salvo que lo pidan).
  `test_menu_opciones.py` pulsa los botones reales.
- Si cambias algo del resumen de `_paso_confirmar`, replica el cambio en `_campos_editables`
  (mismo orden y condiciones) o el campo quedará sin poder editarse.
- Si agregas un elemento a este estilo, agrégalo también a `filas`/`l3` (cuadro de
  datos) o el cuadro no lo mencionará.
- `test_validacion_indirecta.py` (valores calculados a mano), `test_seccionador.py` y `test_menu_opciones.py`.
- Herramientas: NUNCA uses `pkill -f <patrón>` con un patrón que aparezca en tu
  propio comando de shell (se mata a sí mismo y no ejecuta nada).

## Diagrama de CONEXIONES: auditoria de oct/2026
El usuario dijo "el diagrama de conexiones no lo estas haciendo bien" (sin detalle). Se
renderizaron y revisaron a mano los casos principales; errores REALES encontrados y corregidos
(todos visuales/de topologia, ninguno cambia colores ni la numeracion de bornes):
- **Semi/indirecta**: los secundarios de los 3 TC bajaban por las MISMAS dos columnas
  (`tc_x±1`): conductores de R, S y T uno encima de otro, parecian empalmados entre fases; en
  semidirecta el cable de tension VA nacia SOBRE el de corriente IA (un cortocircuito dibujado).
  Ahora cada salida del secundario (S1 izq. "cierre", S2 der. "in") sale por abajo del circulo y
  toma una columna PROPIA (`tc_xs`; la fase de arriba, la mas exterior -> los codos no se cruzan).
- **Indirecta**: el cable de tension salia de la linea PRIMARIA del TP (como si el TP no
  estuviera en el circuito) y el neutro del medidor, de la linea N primaria. `_pt()` ahora dibuja
  primario (baja de la fase y vuelve por la izquierda a N, con puntos de empalme) y secundario con
  terminales 'a' (-> medidor) y 'b' (-> barra BN, comun, **a tierra**). Cada TP cuelga DENTRO de su
  franja (antes TP-S caia sobre la linea de la fase T).
- **Aron (tri3h)**: habia un cable de neutro que nacia en el aire y el TP iba a un punto flotante.
  Ahora 2 TP en conexion **V** (R-S y T-S, sin neutro; cierra el pendiente "2 TP linea-linea"),
  la referencia (borne 5) sale de la barra BN, y se agrego el cable que faltaba del S1 del TC-T al
  borne C2 del bloque (el secundario del TC-T tenia una salida abierta). **Confirmar con el usuario**
  que ese cable es lo correcto en su esquema Aron.
- **Rieles**: algunos corrian a 1 unidad de la linea de fase S y se leian como parte de ella; ahora
  todos van DEBAJO de la barra BN (`y_bus - 3`). Semidirecta: la tension se toma de una derivacion
  con punto de empalme por conductor (N a la izquierda, R a la derecha: cero cruces entre ellas).
- **Directa**: en monofasica simetrica la linea de neutro de acometida y la de carga compartian y
  entre los bornes 2 y 3 -> parecia un puente continuo que se salta el medidor. Si la salida queda a
  la izquierda de la entrada (`si_ < ei_`) la linea de carga baja a otra altura (`lane_y_out`).
  Ademas: bobinas dentro de la caja del medidor, rotulos de borne al lado del cable (no tachados),
  rotulos ACOMETIDA/CARGA arriba de su barra, y se quito una linea punteada de "tap V+" que iba
  exactamente encima del cable de fase.
- **Regla**: un cruce SIN punto no es conexion; un empalme lleva punto. Toda nueva derivacion debe
  llevar punto y su PROPIA columna vertical -- nunca compartir x con otro conductor.
- `test_conexiones.py` recoge las lineas dibujadas y comprueba: ningun par de conductores distintos
  comparte un tramo colineal (panel izquierdo en semi/indirecta; TODO el dibujo en directa), "in" ->
  borne derecho / "cierre" -> izquierdo con el numero esperado de secundarios conectados, y barra BN
  con tierra de la que arranca la referencia. Se verifico que FALLA contra el codigo anterior
  (copia en el historial de git: commit previo a esta seccion).
**PENDIENTE -- NO tocado, necesita confirmacion del usuario** (son convenciones, no errores obvios):
1. **RA8**: `meter_terminals(sistema, norma)` ignora `norma`; con RA8 el neutro se dibuja como
   borne **11** (CENS), pero la convencion fija de este archivo dice **10 para RA8**; y el bloque se
   rotula "(B1-B26)" con numeracion tipo CENS. (Tambien el pendiente "numeracion exacta B1-B26".)
2. **Con respaldo (semi/indirecta)**: el tramo bloque -> medidores sigue enredado (cables de retorno
   punteados rodeando el bloque como cajas, rotulos "3->9" ilegibles, haz de cables cruzados). El
   panel izquierdo SI se limpio. Rehacer ese canal es un cambio mayor.
3. **Directa con respaldo**: solo cambia el subtitulo ("PRINCIPAL + RESPALDO"); NO dibuja el segundo medidor.
4. Los cables "in" llegan al borne DERECHO del bloque pasando POR DETRAS del borne izquierdo y de la
   barra (regla confirmada, pero visualmente parecen terminar en el izquierdo).
5. Los cortocircuitadores de corriente se dibujan como barra gruesa continua (= cerrados); en medida
   normal deberian estar abiertos -- confirmar que se quiere mostrar el estado de servicio.
6. `bornes_medidor_colombia.py` (referencia, no la importa nadie) pone S=amarillo y T=azul, al reves
   de la convencion de colores de este archivo (S azul, T amarillo).

## Unifilar de frontera: campos de acta (oct/2026)
Anexo pedido por el usuario ("CAMPOS NUEVOS EN EL ESQUEMA ... VARIANTES A–D ... PRUEBAS e–j"). Todos
los campos son OPCIONALES; sin ellos nada cambia respecto a lo anterior. Su base ("los 4 JSON anteriores")
no estaba disponible, asi que lo no especificado se decidio asi (cambialo si no es lo que querias):
- **Campos del cfg**: `transformadores` (lista de `{kva, tipo, uso}`; un `transformador` suelto = lista de
  uno), `configuracion_transformadores` ('paralelo' por defecto con 2+ | 'independientes'),
  `planta_respaldo` `{existe, kva, transferencia}`, `ubicacion_medida` ('BT'|'MT'; por defecto MT si
  indirecta, BT en los demas), `celda_medida` `{existe, tipo, estado}`. "-", "n.i", "n/a" o vacio = no
  informado (`_t1` en el motor, `_dato` en bot.py). Helpers en `diagram_engine.py` (antes de
  `draw_unifilar_indirecta_pro`): `_trafos_de`, `_planta_de`, `_celda_de`, `_ubic_medida`, `_clasif_creg`,
  `_resumen_trafos`, `_planta_simbolo`. **Tres renderers los leen**: no los toques por separado.
- **2+ transformadores** -> `draw_unifilar_frontera` (despacho al inicio de `draw_unifilar_generico`).
  NO es la subestacion multi-celda (`n_trafos>=2` sin `transformadores`, que sigue igual): aqui cada
  TRFi lleva su FUi desde el barraje MT. *Paralelo*: secundarios a un barraje BT comun, luego TC/BKR1/
  carga. *Independientes*: cada uno con su barraje/BKR/carga; MED1 solo en el ramal de esta frontera
  (el primero NO compartido, que se dibuja primero a la izquierda conservando su numero TRFk) y el resto
  punteado gris "(fuera de esta frontera)". Maximo 4 (`_TRAFOS_MAX`) + nota "+N transformador(es) no
  mostrado(s)". La insignia COMPARTIDO y el "Ramal de otro usuario" salen solo en el trafo compartido.
  Clasificacion CREG 038 en el cuadro: SUMA de kVA (paralelo) o kVA del ramal medido (independientes).
- **Planta de respaldo**: generador "G" + ATS (o "TRANSFERENCIA MANUAL") conectados al nodo de carga
  DESPUES de BKR1 y de la medida; rotulo "Planta de respaldo (no medida por MED1)" + kVA o "kVA no
  informado"; fila en el cuadro. En frontera y en el unifilar "limpio" va a un costado del nodo de carga
  (izquierda en frontera, derecha en el limpio); `draw_unifilar_generico` la dibuja con `_planta_simbolo`.
  El cable se dibuja en TRAMOS (nodo -> ATS -> G), nunca por detras de un simbolo ni de su texto.
- **Celda de medida (MT)**: recuadro violeta (`_VIOLETA`) que encierra TC + TP con "CELDA DE MEDIDA – <tipo>";
  `existe=false` en MT -> TC/TP sin recuadro y nota "Sin celda de medida". Los rotulos "Sec. TC" y
  "secundarios a tierra" se colocaron FUERA del borde del recuadro (el detector de tests ya lo vigila).
- **Ficha = "cuadro de datos"** (el repo no tiene un elemento llamado "ficha"). Fila "Punto de medición:
  lado BT del transformador" solo con ubicacion BT + trafo (informativa; no cambia el dibujo ni la
  clasificacion). La fila de clasificacion CREG solo existe en el renderer de frontera.
- **Pegamento en `bot.py`**: `_PDF_PROPS_MEDIDA` (esquema estricto con objetos anidados via `_pdf_objeto`),
  `PROMPT_PDF` (tabla acta -> campo; "-"/"n.i" = vacio), `_cfg_desde_pdf` (sanea todo, deriva
  `n_trafos`/`trafo_kva_list`/`trafo_uso`/`trafo_tipo`, `instalacion='trafo'` si hay transformadores,
  'paralelo' por defecto con aviso en "Supuse"), `PROMPT_DIAGRAMA` (campos opcionales, "no los preguntes"),
  `_caption` y `_resumen_medida` (citan trafos/planta/celda). `_verificar_coherencia`: con 2+
  `transformadores` NO aplica las reglas de multi-celda (no fuerza `exclusivo`, no avisa de seccionador/
  proteccion general ni de gabinete), deriva `instalacion`/`trafo_uso`/`trafo_kva` desde la lista y
  corrige `ubicacion_medida='MT'` con directa/semidirecta (BT) avisando.
- **`parser.py` (texto libre) SI los reconoce** (`_extraer_planta`, `_extraer_trafos`, `_extraer_acta`; solo `re`).
  Bug real que lo motivo: el usuario pidio algo con varios transformadores / planta / celda por texto y el bot
  devolvio un unifilar de UN trafo "directa" sin avisar -- el parser ignoraba esas frases y, peor, leia "planta
  de respaldo" como MEDIDOR de respaldo (`respaldo=True`, que es otra cosa). Ahora:
  - **planta**: "planta de respaldo|emergencia|electrica", "generador", "grupo electrogeno", "planta 150 kVA";
    kVA de su clausula (hasta coma/punto/" y "), "transferencia automatica|manual" (o ATS), "sin planta".
    Su clausula se QUITA del texto antes de buscar `respaldo` y el kVA del trafo (si no, el 150 de la planta
    terminaba como kVA del trafo y "respaldo" activaba el segundo medidor).
  - **varios trafos**: "2|dos transformadores" (el numero no puede ser el denominador de una relacion: "200/5 trafo
    300 kVA" NO son 5 trafos), lista de kVA ("300 y 150 kVA", "300 kVA y 150 kVA", "trafo 1 de 300 kVA, trafo 2 de
    150 kVA"), "en paralelo" / "independientes", y cual es compartido ("trafo 2 compartido", "el segundo...",
    "uno de ellos" -> supone el ULTIMO y lo dice en `entendido`; "compartido" a secas -> todos, tambien avisado).
    Sin kVA -> `faltante`. Con 1 trafo sigue por `trafo_kva` (nada cambia).
  - **ubicacion** ("medida en MT|BT|media tension|baja tension|lado de alta") y **celda** ("celda de medida
    AE319 estado bueno", "sin celda").
  - Regla vieja que se conserva: "compartido" sin tipo de medida explicito fuerza `tipo='directa'`.
  - Prueba: `test_frontera.py` (parser + texto -> coherencia -> dibujo sin textos pisados) y un fuzz de 3.000
    frases aleatorias (parser + `_generar`) sin excepciones.
- **Trafo COMPARTIDO con gabinete en el renderer generico** (`draw_unifilar_generico`): el recinto punteado
  cruzaba rotulos y hasta los circulos de los medidores. El detector de `test_frontera.py` (que ahora usa SOLO
  la caja del texto: en un `Annotation`, `get_window_extent` suma la flecha y daba falsos positivos) lo encontro
  en 8 de 16 combinaciones. Arreglos: con gabinete, "+ N medidores mas" y "ESTE MEDIDOR" van FUERA del recinto
  (la flecha si puede cruzar el borde); el fondo del recinto baja para cubrir el rotulo MEDIDOR/RESPALDO;
  "GABINETE COMPARTIDO" va encima del borde superior (a la derecha invadia el cuadro de datos); en directa +
  PRINCIPAL/RESPALDO el recinto mide xc +- 25 (antes xc +- 18 cortaba los circulos), la barra se ensancha con
  el y el eje se corre a `xc = 28` (con 22 el borde izquierdo quedaba fuera del lienzo y se recortaba).
  La prueba tambien comprueba que el recinto no quede recortado por el borde del eje.
- Verificado: `test_frontera.py` (escenarios e–p sin textos superpuestos, revisados a ojo), `test_pdf.py`
  (casos de acta, incl. valores hostiles) y fuzz de 400 cfgs con los campos nuevos. NO verificado en vivo
  (sin API key): que el modelo extraiga bien de un acta real; probar con un PDF verdadero tras el deploy.

## Unifilar de gabinete compartido (oct/2026)
Pedido: el usuario describio por el dialogo IA "medida directa, MT 13,2 kV, transformador interno en subestacion, gabinete interior
compartido con 4 medidores mas, totalizador posterior al medidor, 220 V" y el bot devolvio solo "barraje 220 V -> medidor -> carga";
Claude Chat, con el mismo texto, armo un plano horizontal completo (`unifilar_medida_directa.pdf`) y dijo "asi lo quiero". Dos causas:
(1) el renderer no tenia ese plano (el generico dibuja una rama vertical corta), (2) la IA (Haiku) dejo fuera del JSON lo que el usuario
SI dijo. Ademas la correccion "no mostro el cuadro de lo compartido con 4 mas" caia en la consulta normativa (Gemini, timeout).
- **Segunda ronda (mismo dia): "no me genero el Unifilar tal cual como envie en la foto" + el codigo del ejemplo.** Se corrio el script
  del usuario y se comparo con el bot: la estructura era la misma pero habia diferencias reales (texto del bajante "Bajante en cable /
  monopolar (3 × 1/C)", subtitulo sin "Sistema ... hilos", "(verificar tensión BT)", nota 2, rotulo del totalizador en 2 lineas, guion
  de "13,2 kV – 3F" perdido, proporciones, `posicion_medida`). `draw_unifilar_gabinete` se REESCRIBIO sobre las coordenadas del script
  (barraje en y=62, trafo en (30, 52,5/47,5), gabinete desde x=76, otros usuarios 17 u de ancho, ESTE medidor en la posicion
  `posicion_medida`...). **Escala: ~12,9 u por pulgada** (`_GAB_UPI`), NO 10: el script usa `subplots` con margenes por defecto +
  `bbox_inches="tight"`, asi que su figura de 20,6 in muestra los datos en ~16 in; con 10 u/in el texto salia mas chico que en la foto.
  `test_gabinete.prueba_fidelidad` guarda los textos del script (`TEXTOS_EJEMPLO`, `NOTAS_EJEMPLO`) y exige que con los mismos datos
  (sin `tension_bt` -> 208-120 V asumida, bajante 'monopolar') el plano traiga EXACTAMENTE los mismos. **Unicos retoques respecto al
  ejemplo** (defectos del original): "SUBESTACION INTERIOR" y "SPT neutro BT y masas" ya no los cruza una linea; los rotulos del medidor
  y del totalizador van FUERA del recuadro azul (alli cruzaban su borde; el recuadro mide 22 u = igual que la carga); el hueco de 1 u
  entre el medidor y el totalizador se cerro. Con `tension_bt` dado por el usuario NO se rotula "asumida" ni "(verificar tensión BT)"
  (el script lo hacia siempre). Si el usuario pide "tal cual", NO cambies posiciones/tamanos/textos: compara contra el script primero.
- **Tercera ronda: "compartido con 8 solo dibuja 2" y "no indicas la media tension".** Causas reales (reproducidas):
  (1) `parse_spec` no entendia "compartido con 8" a secas (ni "entre 9", "somos 9", "otros 8", ", 8 usuarios") -> cantidad vacia ->
  2 posiciones de EJEMPLO; ahora `_extraer_gabinete` cubre esas formas (con N => OTROS N; "entre/por N", "somos N", "N en total",
  "gabinete de N medidores" => total, N-1) sin confundir "con 4 hilos" / "con 100 A"; y si la IA deja `trafo_n_usuarios` vacio, el
  numero suelto con que el usuario respondio "¿cuantos usuarios comparten?" se toma de la conversacion (`_otros_desde_respuesta`).
  (2) el motor DIBUJA todas las posiciones hasta 12 otros usuarios (`_GAB_MAX_OTROS`; con >6 las posiciones se juntan a 14,5 u) y solo
  resume el resto en "+N medidores mas" (antes el tope era 5). (3) la MT se perdia: `_extraer_vmt` entiende "13200 V", "13.200 voltios",
  "tension media 13,2", "MT 13200" (no confunde 220 V, kVA ni "13200/120"); `_kv_de` acepta esos formatos (un valor sin unidad solo
  vale entre 1 y 69 kV); y `_verificar_coherencia` ya NO descarta `v_mt` en un punto compartido: si hay MT dada e `instalacion != 'trafo'`
  la pasa a 'trafo' (red MT + trafo) y lo avisa. `v_mt` se normaliza a "13.2 kV". El recuadro azul deja ahora 1,5-3 u de margen a las
  posiciones vecinas (con `posicion_medida` en medio quedaba pegado).
- **Cuarta ronda: "el transformador puede ser trifásico y la medida mono o bifásica".** Causas reales (reproducidas): (1) `parse_spec`
  lanzaba "Sistema ambiguo" con "medida bifásica, transformador trifásico" (veía las dos palabras como dos sistemas) -> el dialogo
  perdia TODO lo del gabinete (la red de seguridad cae si parse_spec lanza) y, peor, el fallback ponia `trafo_tipo` de la primera fase
  nombrada; (2) `draw_unifilar_gabinete` derivaba barraje, acometida, bajante MT y rotulos del `sistema` de la medida.
  Ahora: `parser._fase_trafo` saca la fase dicha JUNTO a "transformador/trafo" ("trafo trifasico", "trafo de 150 kVA trifasico",
  "transformador es trifasico") antes de buscar el sistema de la medida (`_sistemas_dichos`; "bifasica 3 hilos" ya no es tri3h);
  `parser.fases_dichas(texto)` = (medida, trafo) tal como se dijeron. Motor: `sis_bus` (barraje + acometida + secundario + marcas del MT, lo
  fija `trafo_tipo`: trifasico -> 3F + N, bifasico -> 2F + N, monofasico -> 1F + N, o 2F + N si la medida es bifasica = punto medio) vs
  `sistema` (ramal de ESTE usuario: marcas, polos del totalizador, "Medidor bifásico", kWh/kVArh). Con fases distintas el subtitulo dice
  "Medida bifásica 3 hilos", el ramal lleva "2F + N" y una nota explica la derivacion; con `_bt_texto(cfg, sis_bus, sistema)` un "120"
  suelto con trafo trifasico = "208-120 V". Sin `trafo_tipo` y medida mono/bifasica NO se inventa trifasico: se dibuja segun la medida y
  la nota 4 dice "Fases del transformador sin indicar" (con medida tri4h, igual que siempre, sin nota). Medida trifasica + trafo
  mono/bifasico es imposible: `_verificar_coherencia` lo pasa a trifasico y avisa (el motor tambien, con nota). `_completar_con_parser`: lo
  que el usuario DIJO de las fases manda sobre el JSON de la IA (el ultimo mensaje gana) y solo si lo dijo explicitamente (no rellena
  `trafo_tipo` con el fallback del parser). `PROMPT_DIAGRAMA` y `PROMPT_PDF` lo explican (sistema = medida, `trafo_tipo` = trafo) y
  la IA pregunta UNA vez la fase del trafo si la medida es mono/bifasica y no la dijo. Generico: `Dyn11` sigue al trafo, no a la medida.
  No verificado en vivo: que Haiku siga la regla del prompt (la red de seguridad del parser la cubre cuando el usuario lo escribe).
- **`draw_unifilar_gabinete`** (coordenadas del ejemplo, ver arriba; `y` hacia arriba, 110 u de alto + notas). Se despacha desde `draw_unifilar_generico`
  (orden: frontera -> gabinete -> indirecta "pro" -> detallado) cuando `_gabinete_compartido(cfg)`: `tipo=='directa'` y
  (`trafo_uso=='compartido'` o `trafo_n_usuarios > 0`). Semidirecta/indirecta compartidas siguen con el renderer de siempre.
  Dibuja: barra de RED MT -> bajante -> [seccionador MT] -> trafo (con SPT del neutro) -> acometida BT -> gabinete con barraje BT, ESTE
  medidor en recuadro azul (medidor -> totalizador -> carga) y los demas usuarios punteados. Recuadro "SUBESTACION" solo con `ubicacion_trafo` 'interior' o sin dato (poste/exterior/camara: sin recuadro, como el "externo" del ejemplo) /
  "GABINETE DE MEDIDA - N MEDIDORES (INTERIOR)" segun `trafo_gabinete`; sin `instalacion='trafo'` se omite la subestacion.
- **Regla "no inventar"**: lo que no se sabe (kVA del trafo, amperaje del totalizador, clase del medidor) se rotula `___ (por definir)`
  y se lista en NOTAS. NO se dibuja seccionador salvo `seccionador` explicito, ni pararrayos/CC fusibles (el ejemplo no los tenia y el
  usuario pidio "tal cual"; `dps_cantidad` solo sale como nota). Totalizador solo con `totalizador` o con proteccion dada.
  Tension BT: `_bt_texto` (`tension_bt`/`v_bt`; sin dato se asume una habitual y se avisa en una nota).
- Campos nuevos del cfg (todos opcionales): `ubicacion_trafo` ('interior'|'poste'|'exterior'|'camara'), `totalizador` ('antes'|'despues'),
  `clase_medidor`, `bajante_mt` ('monopolar'/'tripolar' -> "Bajante en cable / monopolar (3 × 1/C)"; sin dato NO se inventa la formacion),
  `posicion_medida` (1..N, lugar de ESTE medidor de izquierda a derecha; invalida o con mas de 13 medidores -> primero); `trafo_n_usuarios` = OTROS medidores (el total es N+1); con mas de 12 otros se dibujan 12 posiciones y la
  ultima dice "+N medidores mas"; sin cantidad se dibujan 2 de ejemplo y una nota lo dice. Parser: `_extraer_gabinete`.
  `respaldo` dibuja dos medidores en el recuadro azul.
- **Red de seguridad `_completar_con_parser(ia_cfg, textos_del_usuario, sobrescribir=False)`** (bot.py): se llama en `_dialogo_diagrama`
  al recibir DIAGRAMA_LISTO. Lee el texto del usuario con `parse_spec` y RELLENA lo que la IA dejo vacio (nunca pisa lo que la IA puso);
  si el usuario dijo un punto compartido con cantidad explicita fuerza `trafo_uso='compartido'` e `instalacion='trafo'` si menciono
  transformador/subestacion/MT. Con `sobrescribir=True` (correcciones) el texto del usuario gana en `_CAMPOS_GABINETE`.
  Nunca lanza. Si agregas un campo que el parser lea y la IA pueda perder, agregalo a `_CAMPOS_GABINETE`.
- **`PROMPT_DIAGRAMA`**: nuevas secciones "GABINETE / PUNTO COMPARTIDO" (mapear lo dicho al JSON, "N medidores en total" = N-1 otros, NO
  preguntar kVA/amperaje/clase/BT) y "CORRECCION DE UN DIAGRAMA YA GENERADO"; `tension_bt` ya no es "solo barraje". Sigue siendo
  byte a byte estable (cache).
- **Correcciones** (`_es_correccion_diagrama` / `_corregir_diagrama`, enganchadas en `_procesar_texto` antes de la consulta normativa):
  texto <= 400 caracteres, hay `ultimo_cfg` de hace <= 20 min (`ultimo_ts`, lo fija `_enviar_foto`), cliente Claude configurado, un
  verbo de correccion ("no mostro", "falta", "agrega", "quita", "cambia"...) + un objeto del diagrama (gabinete, totalizador, kVA...),
  sin palabras de normativa (RETIE/CREG/resolucion...), y las preguntas con "?" solo si empiezan por "puedes/podrias". Siembra
  `historial_diagrama` con `{"sembrado": True, "text": "DIAGRAMA ANTERIOR (JSON): ..."}` y deja `modo_diagrama_ia` activo (si la IA
  pregunta algo, la respuesta sigue por el mismo dialogo). Los textos sembrados no los lee `_completar_con_parser`.
- `_verificar_coherencia`: con otros usuarios y sin `trafo_uso` -> 'compartido'; `trafo_gabinete` sin decir -> red abierta (avisado una
  vez); sin cantidad de usuarios -> avisa que dibujo 2 de ejemplo. `_caption` resume "Punto compartido: N medidores (k mas) · gabinete".
- Corregido de paso: el boton "Diseño de diagrama" del menu comprobaba `_genai_client` (Gemini) en vez de `_claude_client`, que es el
  que usa el dialogo desde la migracion.
- **No verificado en vivo** (sin API key): que Haiku siga el prompt nuevo; si deja de llenar el JSON, la red de seguridad lo cubre
  para las frases que el parser entiende. Si pasa seguido, probar `CLAUDE_MODEL_DIALOGO=claude-sonnet-5` en Render.
- Fuera de alcance de esta pasada: el PDF no extrae `ubicacion_trafo`/`totalizador`/`bajante_mt`/`clase_medidor` (usa los campos que ya
  tenia); la salida "conexiones" no cambio.

## Convenciones fijas (no cambiar sin pedir)
- Colores por fase: **R rojo (#D32F2F), S azul (#1565C0), T amarillo (#F9A825), N gris, tierra verde**.
- Mapeo medidor 3 elem (forma 9S): `1 IA · 2 VA · 3 IA' · 4 IB · 5 VB · 6 IB' · 7 IC · 8 VC · 9 IC' · N(10 RA8 / 11 CENS)`.
- 2 elem (Aron): corrientes en R y T, tensión de referencia en S.
- Normas base: **CENS Cap. 6** (bornera 13 term., neutro=11) y **PA-NC-RA8** (bornera 1-10, B1-B26).
- Simbología unifilar: **IEC/UNE 60617**. Todo unifilar lleva "plano de simbología" (EXCEPCIÓN pedida por el usuario: el estilo pro de indirecta, ver sección arriba).
- Estilo del unifilar (v2, tras research de SLDs profesionales reales): NADA
  de cajas con degradado/sombra/estilo "app UI" — eso se ve como mockup de
  interfaz, no como plano de ingeniería. Un unifilar profesional real (ETAP,
  AutoCAD Electrical, planos as-built de utility) es minimalista: líneas
  finas negras, símbolos geométricos simples, sin relleno de color salvo
  las fases. El medidor de energía se dibuja como **círculo con "kWh"**
  (misma convención que un amperímetro = círculo con "A"), NUNCA como caja
  oscura con pantalla LCD. El bloque de prueba es un rectángulo blanco de
  borde fino, sin degradado azul. Antes de agregar "pulido visual" a un
  símbolo, pregúntate si un ingeniero reconocería ese símbolo en un plano
  real — si no, es decoración, no diseño.
- En la entrada MT del unifilar (`draw_unifilar_generico`) NO se dibuja un
  "Seccionador MT" separado antes de los CC fusibles: los cortacircuitos
  fusibles YA sirven como elemento de seccionamiento (se abren en vacío)
  además de proteger. Poner ambos es redundante e incoherente — no lo
  reintroduzcas salvo que un caso real lo justifique explícitamente.
- TC (serie) vs TP (paralelo) en el unifilar se diferencian a propósito:
  línea del TC más gruesa + etiqueta "(serie)"; línea del TP más delgada +
  etiqueta "(paralelo)". El TC es el que lleva la corriente hacia la medida;
  no iguales el grosor de ambas líneas "para que se vea simétrico".

## Estado / pendientes (v2)
- [ ] **Diagrama fasorial** (tercera salida del bot).
- [ ] Numeración exacta de bornes B1–B26 (norma RA8) sobre cada terminal del bloque.
- [ ] 2 elementos: opción de 2 TP línea-línea (hoy dibuja 1 TP por fase).
- [x] DPS/pararrayos y puesta a tierra del neutro en el caso con transformador
      (directa/semidirecta+trafo; indirecta ya los tenía en su punto de medida).
- [ ] Exportar a PDF y cajetín de proyecto.
- [ ] Tests unitarios del parser y de mapeo de terminales.

## Cómo correr
```
pip install -r requirements.txt
export BOT_TOKEN="..."   # de @BotFather
python bot.py
# pruebas:
python test_e2e.py
python diagram_engine.py
```

## RAG (File Search) sobre el texto real de RETIE/CREG
`bot.py` ya tiene el código para usarlo (`RETIE_STORE_NAME`, `types.FileSearch`
en `_consulta_retie`), pero si esa variable de entorno no está configurada el
bot responde SOLO con los "datos memorizados" del prompt (aproximaciones que
hay que mantener a mano — ver el resto de este documento, es la fuente de
varios de los bugs que se han corregido).

**Importante — esto YA se habia hecho en una sesion anterior** (commits
`9834dab`/`420014c`/`8528f2a`, mensaje "RAG con CREG y RETIE indexados,
deploy Render 24/7"), antes del historial que se resume en este documento.
El store `fileSearchStores/retie2024-r0u1h57kkhhz` (display name
`retie-2024`) ya existe y ya tenia 11 documentos indexados (RETIE 2024
Libros 1-4 completos + varias resoluciones CREG, algunas con el display
name mal escrito -- ej. "Creg015-2014" y "Creg038-2018" que en realidad
parecen ser 015/2018 y 038/2014 intercambiados, revisar si se retoca este
tema) -- y `RETIE_STORE_NAME` con ese valor ya estaba exportado en
`~/.zshrc` de la maquina de desarrollo. Es MUY probable que Render ya tenga
esa misma variable configurada desde ese despliegue anterior. Antes de decirle
al usuario "vamos a activar el RAG desde cero", verifica primero si ya esta
activo (probar una consulta especifica en el bot real y ver si cita
pagina/articulo con precision, o listar los documentos del store con
`client.file_search_stores.documents.list(parent=store_name)`).

El script viejo que existia en `setup_retie_store.py` (antes de esta sesion)
creaba un **Context Cache** (`client.caches.create`, variable
`RETIE_CACHE_NAME`) -- un mecanismo DISTINTO y ya no usado: `bot.py` nunca
lee `RETIE_CACHE_NAME` en ningun lado, asi que ese script estaba
completamente desconectado del bot real (probablemente un intento anterior
al que finalmente se uso: File Search Store). Se reemplazo por una version
que usa `client.file_search_stores` (consistente con lo que `bot.py` si lee),
y que reutiliza el store existente si `RETIE_STORE_NAME` ya esta en el
entorno en vez de crear uno nuevo:
```
export GEMINI_API_KEY="..."
python3 setup_retie_store.py normativa/*.pdf
# imprime RETIE_STORE_NAME=fileSearchStores/xxxxx -- eso va en Render
```
El script mismo documenta (en su docstring) los links oficiales de descarga
de RETIE 2024 compilado (con la modificación de 2026 ya incorporada) y CREG
038/2014 y 015/2018 -- pero antes de subir estos de nuevo, revisa primero
qué ya hay en el store (ver arriba) para no duplicar contenido que ya estaba
indexado. Para agregar un documento nuevo (ej. una resolución CREG que salga
más adelante), exporta `RETIE_STORE_NAME` con el valor ya existente y vuelve
a correr el script solo con el archivo nuevo — no borra lo que ya había
indexado. Almacenamiento es gratis en la API de Gemini; solo se cobra la
indexación (embeddings, una vez por documento) y los tokens de contexto
recuperados en cada consulta (como tokens normales de entrada).

## `/ultimo` y plantillas guardadas (`/guardar`, `/plantillas`, `/cargar`)
`_enviar_foto(mensaje, cfg, ctx=None)` ahora guarda el cfg YA CORREGIDO por
`_verificar_coherencia` en `ctx.user_data["ultimo_cfg"]` cada vez que se
genera un diagrama exitosamente (los 3 call sites -- dialogo IA, texto libre,
menu de botones -- ya pasan `ctx`). `/ultimo` carga ese cfg en la pantalla de
confirmacion (reusa `_paso_confirmar(target, cfg, edit=False)`, el mismo
mecanismo dual edit/reply que ya se agrego para "Editar") -- se puede
regenerar tal cual o tocar "Editar" para cambiar un dato antes ("el mismo
pero con 300 kVA") sin repetir todo el flujo del menu.

Las plantillas (`/guardar nombre`, `/plantillas`, `/cargar nombre`) son
DISTINTAS de `ultimo_cfg`: se guardan en una hoja nueva ("Plantillas") del
MISMO Google Sheet que ya se usa para gestion de usuarios (`SHEET_ID`), NO en
`ctx.user_data` -- esto es deliberado: `ctx.user_data` se pierde en cada
reinicio del bot (Render reinicia seguido en el plan free), asi que guardar
plantillas solo en memoria las haria inutiles en la practica. La hoja
"Plantillas" (columnas `Telegram_ID, Nombre, Cfg_JSON, Fecha`) se crea sola
la primera vez que alguien usa `/guardar` (`_gs_get_plantillas_sheet` hace
`worksheet()` y si no existe la crea con `add_worksheet()` + fila de
encabezado) -- no hay que crearla a mano. `_gs_guardar_plantilla` sobrescribe
si ya existe una plantilla con el mismo nombre PARA ESE usuario (busca por
`Telegram_ID` + `Nombre` antes de decidir `update_cell` vs `append_row`), en
vez de duplicar filas. El cfg se guarda serializado como JSON en una sola
celda (columna C) -- si agregas un campo nuevo al cfg, no hace falta tocar
el esquema de esta hoja, json.dumps/loads ya lo cubre automaticamente.

Todas estas funciones (`_gs_guardar_plantilla`, `_gs_listar_plantillas`,
`_gs_cargar_plantilla`) siguen el MISMO patron de degradacion que
`_gs_sync`/`_gs_set_estado`: si `_gs_get_client()` devuelve `None` (Sheets no
configurado), devuelven `False`/`[]`/`None` en vez de lanzar excepcion, y los
comandos (`cmd_guardar`/`cmd_plantillas`/`cmd_cargar`) le avisan al usuario
que la funcionalidad no esta disponible en vez de fallar en silencio. Son
funciones SINCRONAS (igual que el resto de las `_gs_*`) -- llamarlas siempre
via `loop.run_in_executor(None, lambda: ...)` desde el handler async, nunca
directo con `await`.

Verificado con un cliente de gspread simulado (sin credenciales reales):
guardar -> listar -> cargar (bajo nivel), sobrescribir con el mismo nombre
sin duplicar fila, aislamiento entre usuarios distintos, y los 4 comandos
mas el boton de `/plantillas` de punta a punta.

**Pendiente si el usuario lo pide**: comando para borrar una plantilla
guardada (`/borrar nombre` o similar) -- no se implemento en esta pasada
porque no se pidio explicitamente y `_gs_guardar_plantilla` ya permite
"reemplazar" guardando de nuevo con el mismo nombre, que cubre el caso mas
comun (actualizar una plantilla vieja).

## Botones "Seguir esta consulta" / "Nueva consulta"
Antes, si el usuario preguntaba algo nuevo sin usar palabras clave de
diagrama, `_procesar_texto` asumía automáticamente que era continuación de
la misma consulta normativa y arrastraba `historial_retie` completo —
funciona bien para seguimientos reales, pero si el usuario cambiaba de tema
sin querer (ej. de distancias de seguridad a EPP en alturas) el hilo viejo
se colaba como contexto. `_consulta_retie` ahora agrega, al final de CADA
respuesta (incluida la última parte si `_enviar_largo` la partió en varios
mensajes por el límite de Telegram — por eso `_enviar_largo` ahora acepta
`reply_markup` y solo lo pone en el ÚLTIMO mensaje), dos botones: "🔁 Seguir
esta consulta" (no cambia nada, es solo confirmación explícita) y "🆕 Nueva
consulta" (limpia `historial_retie`). El comportamiento POR DEFECTO no
cambió — si el usuario ignora los botones y sigue escribiendo, el hilo
continúa igual que antes (clasificación automática por palabras clave de
diagrama); los botones son una salida explícita para cuando el usuario
quiere cortar el hilo sin usar `/cancelar` (que también borra todo lo demás)
ni depender de que el texto nuevo tenga o no palabras de diagrama. Al tocar
cualquiera de los dos botones se le quitan del mensaje (via
`edit_message_reply_markup(reply_markup=None)`) para que no se puedan volver
a pulsar por accidente y reabrir/cerrar el hilo dos veces.

## Edición puntual de un campo (pantalla de confirmación del menú)
Antes, la pantalla de confirmación (`_paso_confirmar`) solo tenía "Generar" y
"Reiniciar" — si un solo dato estaba mal, había que rehacer todo el flujo
desde `/menu`. Ahora tiene un tercer botón "✏️ Editar" que lleva a un
submenú con los campos actualmente visibles en el resumen (`_campos_editables(cfg)`
define esa lista y las condiciones de "cuando aplica", en el MISMO orden y
con las MISMAS condiciones que `_paso_confirmar` — si agregas una línea nueva
al resumen, agrega también su entrada aquí o quedará invisible para editar).
Cada campo es "choice" (usa el mismo teclado de opciones que la pregunta
original, callback `editval:<campo>:<valor>`) o "text" (pide el valor por
texto, usando los mismos validadores `_validar_numero`/`_validar_relacion`
que el resto del flujo). Al aplicar el valor (`_aplicar_valor_editado`) NO
se toca `paso_n` ni ningún flag del flujo lineal normal — es un sub-flujo
aislado que siempre termina regresando a `_paso_confirmar`. Casos especiales
manejados ahí: `respaldo` se convierte a bool (`val == "si"`), y
`proteccion_amp` también actualiza el campo legado `interruptor` (para que
seccionador/protección sigan coherentes con lo que lee `diagram_engine.py`,
ver la sección de arriba sobre `proteccion_pos`). Si agregas un campo nuevo
al cfg que tenga esta misma dualidad de "campo real vs. campo legado
espejo", replica ese mismo patrón en `_aplicar_valor_editado`.
Verificado con simulación directa de `on_button`/`on_text` (sin Telegram
real): edición de campo tipo "choice" (tipo de medida), campo tipo "text"
con validación (relación TC, incluyendo el caso de texto inválido que debe
mantener el sub-flujo activo en vez de perderlo), botón "Volver" sin
seleccionar nada, y los dos casos especiales (`proteccion_amp`↔`interruptor`,
`respaldo` bool) — en todos los casos `paso_n` quedó intacto.

## Reglas de trabajo para el agente
- **"Energiza" cada diagrama antes de darlo por bueno — SIEMPRE, no solo la
  primera vez.** No basta con que `draw_conexiones_retie` /
  `draw_unifilar_generico` corran sin excepción ni con que `_verificar_render()`
  confirme un PNG no vacío: eso solo prueba que matplotlib no truena, no que
  el circuito sea coherente. "Energizar" = trazar a mano, elemento por
  elemento, si la secuencia dibujada representa un flujo real y completo para
  el `cfg` dado:
  1. RED → protecciones obligatorias para ese tipo/instalación (pararrayos,
     cortacircuitos/fusibles, seccionador) → trafo (con tierra) si aplica →
     punto de derivación/barraje → bloque de prueba/TC/TP si aplica → medidor
     → carga. Ningún tramo obligatorio puede faltar ni quedar implícito.
  2. Si `trafo_uso='compartido'`: debe quedar señalado explícitamente CUÁL
     medidor es el de este usuario (no basta con dibujar "hay más
     usuarios"; el bug real que motivó esta regla fue que esa rama quedaba
     dibujada EXACTAMENTE encima del TC/bloque/medidor propio, invisible).
  3. Ningún elemento (texto, símbolo, recuadro) puede compartir el mismo
     rango x/y que otro con significado distinto — dos elementos que se
     tapan entre sí no es un detalle estético, es información perdida.
  4. Renderiza el PNG de verdad y revísalo con tus propios ojos (Read del
     archivo) antes de decir que algo quedó corregido — no asumas que un
     cambio de coordenadas "debería" funcionar. Prueba explícitamente al
     menos: exclusivo, compartido+gabinete, compartido+red abierta, y la
     combinación tipo × instalación que estés tocando.
  5. Si encuentras una discrepancia (aunque no te la hayan pedido a ti
     arreglar), no la ignores: es exactamente el tipo de bug que ya se
     coló dos veces en este proyecto (compartido/exclusivo idénticos, luego
     la rama de "otros usuarios" tapada).
- Verifica los diagramas renderizando un PNG y revisándolo antes de dar por hecho un cambio.
- No alteres el esquema de colores ni el mapeo de terminales sin confirmación.
- Mantén `parser.py` sin dependencias (solo `re`).
- Antes de dar por buena una entrega de diagrama (en código, no solo en esta
  sesión): el cfg pasa por `_verificar_coherencia()` (corrige/advierte cruces
  imposibles, p.ej. `v_mt` en directa/semidirecta, o `instalacion=trafo` sin
  `trafo_uso`) y el PNG resultante pasa por `_verificar_render()` (existe y no
  quedó vacío/corrupto) antes de enviarse al usuario. Si agregas un campo
  nuevo al cfg que cambie lo que se dibuja, añade aquí también su chequeo de
  coherencia — de lo contrario dos entradas equivalentes (texto libre, menú,
  diálogo IA) pueden terminar generando diagramas distintos o incoherentes
  con lo que el usuario realmente indicó.
