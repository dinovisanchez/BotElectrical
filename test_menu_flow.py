#!/usr/bin/env python3
"""Test del flujo de menu interactivo (simulación)."""
import sys
sys.path.insert(0, '.')
from parser import DEFAULT, parse_spec
from diagram_engine import draw

# Simular menu flow para DIRECTA
print("=" * 60)
print("TEST 1: DIRECTA + SIMÉTRICO + CONEXIONES")
print("=" * 60)
cfg = dict(DEFAULT)
cfg['tipo'] = 'directa'
cfg['sistema'] = 'tri4h'
cfg['norma'] = 'RA8'
cfg['respaldo'] = False
cfg['asimetrico'] = False
cfg['salida'] = 'conexiones'
try:
    draw(cfg, '/tmp/test_directa_simetrica.png')
    print("✓ Diagram generated: /tmp/test_directa_simetrica.png")
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 2: DIRECTA + ASIMÉTRICO + CONEXIONES")
print("=" * 60)
cfg['asimetrico'] = True
try:
    draw(cfg, '/tmp/test_directa_asimetrica.png')
    print("✓ Diagram generated: /tmp/test_directa_asimetrica.png")
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 3: DIRECTA + RESPALDO")
print("=" * 60)
cfg['respaldo'] = True
cfg['asimetrico'] = False
try:
    draw(cfg, '/tmp/test_directa_respaldo.png')
    print("✓ Diagram generated: /tmp/test_directa_respaldo.png")
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 4: DIRECTA MONOFÁSICA")
print("=" * 60)
cfg['sistema'] = 'mono'
cfg['respaldo'] = False
try:
    draw(cfg, '/tmp/test_directa_mono.png')
    print("✓ Diagram generated: /tmp/test_directa_mono.png")
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ ALL TESTS PASSED")
print("=" * 60)
