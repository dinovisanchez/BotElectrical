# -*- coding: utf-8 -*-
"""Prueba extremo-a-extremo SIN Telegram: texto -> parser -> motor -> PNG.

G1 FIX: los tests ahora usan draw_conexiones_retie() y draw_unifilar_generico(),
que son las funciones reales que usa el bot en produccion.
"""
import os, diagram_engine
from parser import parse_spec

casos = [
    # (descripcion, cfg_override)
    ("indirecta tri4h CENS 200/5 13200/120",             None),
    ("semidirecta tri4h RA8 300/5",                      None),
    ("indirecta tri4h con respaldo 200/5 13200/120",      None),
    ("indirecta tri3h aron 100/5 7620/120",               None),
    ("monofasica directa",                                None),
    # G3: antes causaba ValueError con "trifasica 3 hilos"
    ("trifasica 3 hilos indirecta CENS 200/5 13200/120", None),
    # semidirecta con trafo (via menu, no texto libre)
    ("semidirecta tri4h RA8 300/5",
     {"instalacion": "trafo", "trafo_kva": "50", "trafo_tipo": "trifasico", "tc_amp": "200"}),
]

base = os.path.dirname(os.path.abspath(__file__))
ok = err = 0
for i, (c, override) in enumerate(casos, 1):
    try:
        cfg, ent, falt = parse_spec(c)
        if override:
            cfg.update(override)
        out_cx = os.path.join(base, f"e2e_{i}_conexiones.png")
        diagram_engine.draw_conexiones_retie(cfg, out_cx)
        kb_cx = os.path.getsize(out_cx) // 1024

        out_uni = os.path.join(base, f"e2e_{i}_unifilar.png")
        diagram_engine.draw_unifilar_generico(cfg, out_uni)
        kb_uni = os.path.getsize(out_uni) // 1024

        print(f"[{i}] '{c}' -> {cfg['tipo']}/{cfg['sistema']}/{cfg['norma']} "
              f"respaldo={cfg['respaldo']}  "
              f"conexiones={kb_cx}KB  unifilar={kb_uni}KB  OK")
        if falt:
            print(f"     FALTANTE: {falt}")
        ok += 1
    except Exception as e:
        print(f"[{i}] '{c}' -> ERROR: {e}")
        err += 1

print(f"\nResultado: {ok} OK / {err} ERRORES")
