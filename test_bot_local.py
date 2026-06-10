#!/usr/bin/env python3
"""Test local del bot SIN Telegram - valida que todo funciona."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Simular update de Telegram
class FakeMessage:
    def __init__(self, text):
        self.text = text
    
    async def reply_text(self, msg, parse_mode=None):
        print(f"[BOT REPLY] {msg[:80]}...")
    
    async def reply_photo(self, photo, caption, parse_mode=None):
        print(f"[BOT PHOTO] {caption[:50]}...")

class FakeUpdate:
    def __init__(self, text):
        self.message = FakeMessage(text)
        self.effective_message = self.message

class FakeContext:
    def __init__(self):
        self.args = []
        self.user_data = {}

async def test_procesar_texto():
    """Test de _procesar_texto sin Telegram."""
    from bot import _procesar_texto
    
    test_cases = [
        ("indirecta trifasica 3 elementos norma CENS 200/5 13200/120", "test1"),
        ("semidirecta 3 elementos norma RA8 300/5", "test2"),
        ("directa monofasica", "test3"),
    ]
    
    print("=" * 60)
    print("TEST: _procesar_texto (análisis sin Telegram)")
    print("=" * 60)
    
    for texto, label in test_cases:
        print(f"\n[{label}] Entrada: {texto}")
        try:
            update = FakeUpdate(texto)
            await _procesar_texto(update, texto)
            print(f"✓ Procesado exitosamente")
        except Exception as e:
            print(f"✗ Error: {e}")

async def test_parser():
    """Test del parser."""
    from parser import parse_spec
    
    test_cases = [
        "indirecta trifasica 3 elementos 200/5 13200/120 CENS",
        "semidirecta 300/5 RA8",
        "directa monofasica",
    ]
    
    print("\n" + "=" * 60)
    print("TEST: Parser de especificaciones")
    print("=" * 60)
    
    for texto in test_cases:
        print(f"\nEntrada: {texto}")
        try:
            cfg, ent, falt = parse_spec(texto)
            print(f"✓ Parsed: tipo={cfg['tipo']}, sist={cfg['sistema']}")
            if cfg.get('rel_tc'): print(f"  RTC={cfg['rel_tc']}, RTP={cfg['rel_tp']}")
            if falt: print(f"  Faltante: {', '.join(falt)}")
        except Exception as e:
            print(f"✗ Error: {e}")

def test_diagrams():
    """Test de generación de diagramas."""
    import tempfile
    import time
    import diagram_engine
    
    configs = [
        ("Conexiones", {
            'sistema': 'tri4h', 'tipo': 'indirecta', 'respaldo': False,
            'norma': 'RA8', 'rel_tc': '200/5', 'rel_tp': '13200/120',
            'salida': 'conexiones'
        }, diagram_engine.draw),
        ("Unifilar", {
            'sistema': 'tri4h', 'tipo': 'indirecta', 'respaldo': False,
            'norma': 'RA8', 'rel_tc': '200/5', 'rel_tp': '13200/120',
            'salida': 'unifilar'
        }, diagram_engine.draw_unifilar),
    ]
    
    print("\n" + "=" * 60)
    print("TEST: Generación de diagramas")
    print("=" * 60)
    
    for name, cfg, func in configs:
        print(f"\n{name}...", end=" ", flush=True)
        try:
            t = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            t.close()
            start = time.time()
            func(cfg, t.name)
            elapsed = time.time() - start
            size_kb = os.path.getsize(t.name) // 1024
            print(f"✓ {elapsed:.2f}s ({size_kb} KB)")
            os.remove(t.name)
        except Exception as e:
            print(f"✗ {e}")

if __name__ == "__main__":
    import asyncio
    
    print("\n🧪 TESTS DE BOT LOCAL\n")
    
    # Tests síncronos
    test_diagrams()
    asyncio.run(test_parser())
    
    # Tests async
    asyncio.run(test_procesar_texto())
    
    print("\n" + "=" * 60)
    print("✅ TODOS LOS TESTS COMPLETADOS")
    print("=" * 60)
