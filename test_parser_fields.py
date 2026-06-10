#!/usr/bin/env python3
"""
Demostración: Parser extrae nuevos campos (asimetrico, trafo, interruptor).
"""
import sys
sys.path.insert(0, '.')
from parser import parse_spec

tests = [
    "medida directa asimétrica",
    "directa bifásica",
    "indirecta con transformador de 50 kva",
    "semidirecta con interruptor de 200 amperios",
    "indirecta 3 elementos 200/5 13200/120 con transformador antes del medidor",
]

print("=" * 70)
print("PARSER - Extracción de Nuevos Campos")
print("=" * 70)

for text in tests:
    cfg, entendido, faltante = parse_spec(text)
    print(f"\n📄 Input: \"{text}\"")
    print(f"   tipo: {cfg['tipo']}")
    print(f"   asimetrico: {cfg['asimetrico']}")
    print(f"   trafo_presente: {cfg['trafo_presente']}")
    print(f"   interruptor_pos: {cfg['interruptor_pos']}")
    print(f"   ✓ Understood: {', '.join(entendido) if entendido else 'basics only'}")
