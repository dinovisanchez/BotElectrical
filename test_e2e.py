# -*- coding: utf-8 -*-
"""Prueba extremo-a-extremo SIN Telegram: texto -> parser -> motor -> PNG."""
import os, diagram_engine
from parser import parse_spec
casos = [
    "indirecta trifasica 3 elementos norma CENS 200/5 13200/120",
    "semidirecta 3 elementos norma RA8 300/5",
    "indirecta 3 elementos con respaldo 200/5 13200/120",
    "indirecta 2 elementos aron 100/5 7620/120",
    "monofasica directa",
]
base = os.path.dirname(os.path.abspath(__file__))
for i, c in enumerate(casos, 1):
    cfg, ent, falt = parse_spec(c)
    out = os.path.join(base, f"e2e_{i}.png")
    diagram_engine.draw(cfg, out)
    print(f"[{i}] '{c}'\n     -> {cfg['tipo']}/{cfg['sistema']}/{cfg['norma']} respaldo={cfg['respaldo']}  OK ({os.path.getsize(out)//1024} KB)")
