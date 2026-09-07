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
  - `draw`, `draw_unifilar`, `draw_unifilar_trafo` siguen existiendo en el
    archivo pero son **legacy/no se usan en producción** — no asumas que
    reflejan el comportamiento real del bot; si vas a tocar el motor de
    unifilares, edita `draw_unifilar_generico`.
  - Símbolos IEC: `_u_breaker, _u_disc, _u_fuse, _u_arrester, _u_ct, _u_vt, _u_xfmr, _u_relay, _ground`.
- `parser.py` — `parse_spec(text)` → `(cfg, entendido, faltante)`. Sin dependencias.
- `bot.py` — handlers de Telegram (start/help/menu/diagrama + texto libre + botones).
  `_verificar_coherencia(cfg)` corrige/advierte inconsistencias (p.ej. v_mt en
  tipos BT, trafo sin `trafo_uso`) ANTES de dibujar; `_verificar_render()`
  confirma que el PNG generado no salió vacío/corrupto antes de enviarlo.
- `test_e2e.py`, `test_menu_flow.py`, `test_parser_fields.py` — pruebas locales
  sin Telegram, contra las funciones reales de producción (no las legacy).
- `requirements.txt`, `README.md`.

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
