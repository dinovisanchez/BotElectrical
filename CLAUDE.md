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
  `'compartido'`, agrega un barraje BT explícito con una rama punteada "+ N
  otros usuarios" y, si `trafo_gabinete=True`, un recinto punteado alrededor
  (si es `False`/red abierta, NO se encierra); si es `'exclusivo'` (o no se
  especifica), dibuja la línea directa trafo→medidor sin esa rama.
- Para tipo directa/semidirecta con `instalacion='trafo'` siempre se dibuja
  protección MT (pararrayos ZnO + cortacircuitos fusible) antes del trafo, y
  su puesta a tierra en un ramal lateral (no tapada por la línea principal).
  El conductor se etiqueta en ambos extremos (trafo/red → medidor, y
  medidor → carga), con placeholder `"cal. ?"` si no se especificó.
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

## Estado / pendientes (v2)
- [ ] **Diagrama fasorial** (tercera salida del bot).
- [ ] Numeración exacta de bornes B1–B26 (norma RA8) sobre cada terminal del bloque.
- [ ] 2 elementos: opción de 2 TP línea-línea (hoy dibuja 1 TP por fase).
- [ ] DPS/pararrayos y puesta a tierra del neutro en el caso con transformador.
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
