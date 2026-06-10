# Proyecto: Bot de Telegram — Diagramas de sistemas de medida de energía

## Qué es
Bot de Telegram que actúa como ingeniero de diseño eléctrico. Recibe las
especificaciones de una medida (texto libre, comando o menú) y devuelve:
- **Diagrama de conexiones** (Medidor ↔ Bloque de prueba ↔ TC/TP)
- **Diagrama unifilar** (con símbolos IEC/UNE 60617 y plano de simbología)

## Estructura
- `diagram_engine.py` — motor de dibujo (matplotlib). Funciones públicas:
  - `draw(cfg, out)` → diagrama de conexiones.
  - `draw_unifilar(cfg, out)` → unifilar genérico (indirecta MT / semidirecta BT).
  - `draw_unifilar_trafo(cfg, out)` → unifilar real con transformador ANTES de la medida
    (semidirecta en secundario): RED MT → cortacircuitos → trafo → barra BT → TC → medidor
    + totalizador → carga.
  - Símbolos IEC: `_u_breaker, _u_disc, _u_fuse, _u_arrester, _u_ct, _u_vt, _u_xfmr, _u_relay, _ground`.
- `parser.py` — `parse_spec(text)` → `(cfg, entendido, faltante)`. Sin dependencias.
- `bot.py` — handlers de Telegram (start/help/menu/diagrama + texto libre + botones).
- `test_e2e.py` — prueba local sin Telegram.
- `requirements.txt`, `README.md`.

## Modelo de configuración (cfg)
```
sistema : 'mono' | 'bifasico' | 'tri3h' (2 elem) | 'tri4h' (3 elem)
tipo    : 'directa' | 'semidirecta' | 'indirecta'
respaldo: bool                      # principal + chequeo (1 bloque, 2 medidores)
norma   : 'CENS' | 'RA8'
salida  : 'conexiones' | 'unifilar' | 'ambos'
rel_tc, rel_tp, tension, proyecto : str
# unifilar con trafo:
unifilar_trafo: bool, trafo_kva, trafo_tipo, n_cc, n_tc, interruptor, v_mt, v_bt
# opcionales unifilar: dps (bool), rele (bool), rele_funcs (str ANSI)
```

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
