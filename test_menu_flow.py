#!/usr/bin/env python3
"""Test del flujo de menu interactivo (simulación).

Usa draw_conexiones_retie(), la función real que usa el bot en producción
(draw() está obsoleta, ver diagram_engine.py). El campo de conexión
simétrica/asimétrica se llama 'conexion' en el cfg (no 'asimetrico')."""
import sys
sys.path.insert(0, '.')
from parser import DEFAULT
from diagram_engine import draw_conexiones_retie

# Simular menu flow para DIRECTA
print("=" * 60)
print("TEST 1: DIRECTA + SIMÉTRICO + CONEXIONES")
print("=" * 60)
cfg = dict(DEFAULT)
cfg['tipo'] = 'directa'
cfg['sistema'] = 'tri4h'
cfg['norma'] = 'RA8'
cfg['respaldo'] = False
cfg['conexion'] = 'simetrica'
cfg['salida'] = 'conexiones'
try:
    draw_conexiones_retie(cfg, '/tmp/test_directa_simetrica.png')
    print("✓ Diagram generated: /tmp/test_directa_simetrica.png")
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 2: DIRECTA + ASIMÉTRICO + CONEXIONES")
print("=" * 60)
cfg['conexion'] = 'asimetrica'
try:
    draw_conexiones_retie(cfg, '/tmp/test_directa_asimetrica.png')
    print("✓ Diagram generated: /tmp/test_directa_asimetrica.png")
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 3: DIRECTA + RESPALDO")
print("=" * 60)
cfg['respaldo'] = True
cfg['conexion'] = 'simetrica'
try:
    draw_conexiones_retie(cfg, '/tmp/test_directa_respaldo.png')
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
    draw_conexiones_retie(cfg, '/tmp/test_directa_mono.png')
    print("✓ Diagram generated: /tmp/test_directa_mono.png")
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ ALL TESTS PASSED")
print("=" * 60)
