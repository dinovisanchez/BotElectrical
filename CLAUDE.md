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
  - Símbolos IEC: `_u_breaker, _u_disc, _u_fuse, _u_arrester, _u_ct, _u_vt, _u_xfmr, _u_relay, _ground`.
- `parser.py` — `parse_spec(text)` → `(cfg, entendido, faltante)`. Sin dependencias.
- `bot.py` — handlers de Telegram (start/help/menu/diagrama + texto libre + botones).
  `_verificar_coherencia(cfg)` corrige/advierte inconsistencias (p.ej. v_mt en
  tipos BT, trafo sin `trafo_uso`) ANTES de dibujar; `_verificar_render()`
  confirma que el PNG generado no salió vacío/corrupto antes de enviarlo.
- `test_e2e.py`, `test_menu_flow.py`, `test_parser_fields.py` — pruebas locales
  sin Telegram, contra las funciones reales de producción (no las legacy).
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
sistema : 'mono' | 'bifasico' | 'tri3h' (2 elem) | 'tri4h' (3 elem)
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
# opcionales unifilar: dps (bool), rele (bool), rele_funcs (str ANSI)
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

## Convenciones fijas (no cambiar sin pedir)
- Colores por fase: **R rojo (#D32F2F), S azul (#1565C0), T amarillo (#F9A825), N gris, tierra verde**.
- Mapeo medidor 3 elem (forma 9S): `1 IA · 2 VA · 3 IA' · 4 IB · 5 VB · 6 IB' · 7 IC · 8 VC · 9 IC' · N(10 RA8 / 11 CENS)`.
- 2 elem (Aron): corrientes en R y T, tensión de referencia en S.
- Normas base: **CENS Cap. 6** (bornera 13 term., neutro=11) y **PA-NC-RA8** (bornera 1-10, B1-B26).
- Simbología unifilar: **IEC/UNE 60617**. Todo unifilar lleva "plano de simbología".
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
