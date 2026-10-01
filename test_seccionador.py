#!/usr/bin/env python3
"""Seccionador y norma/circuito: texto libre -> cfg, avisos de coherencia y render.

"antes"   = entre el punto de medida y el trafo (lado MT)
"despues" = aguas abajo del trafo (lado BT)
En indirecta la medida esta en MT (aguas arriba del trafo): "despues de la
medida" queda fisicamente ENTRE la medida y el trafo -> cfg "antes"."""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
logging.disable(logging.CRITICAL)
from parser import parse_spec, DEFAULT
import bot

CASOS = [
    ("indirecta trafo 700 kva con seccionador despues de la medida", "antes"),
    ("indirecta trafo 700 kva seccionador tripolar 13.2 kV despues de la medida", "antes"),
    ("semidirecta trafo 150 kva seccionador despues de la medida", "despues"),
    ("indirecta trafo 700 kva seccionador antes del trafo", "antes"),
    ("indirecta trafo 700 kva seccionador despues del transformador", "despues"),
    ("semidirecta trafo 150 kva seccionador lado BT", "despues"),
    ("indirecta trafo 700 kva seccionador en MT", "antes"),
    ("indirecta trafo 700 kva con seccionador", "antes"),          # sin posicion: tipico
    ("indirecta trafo 700 kva sin seccionador", None),
    ("indirecta trafo 700 kva", None),
    ("indirecta trafo 700 kva seccionador antes, proteccion despues del medidor", "antes"),
    ("Seccionador DESPUÉS del trafo, 13,2 kV indirecta trafo 700 kva", "despues"),
]

def main():
    malos = 0
    for txt, esperado in CASOS:
        got = parse_spec(txt)[0].get("seccionador")
        ok = got == esperado
        malos += not ok
        print("OK  " if ok else "MAL ", f"{got!r:10} esp {esperado!r:10} | {txt}")

    # Un circuito/punto de conexion llamado "RA8" NO es la norma RA8
    for txt, norma, cto in [
        ("unifilar indirecta CENS 30/5 13200/120 trafo 700 kva circuito RA8", "CENS", "RA8"),
        ("unifilar indirecta CENS 30/5 13200/120 trafo 700 kva cto: RA8", "CENS", "RA8"),
        ("unifilar indirecta CENS 30/5 13200/120 trafo 700 kva punto de conexion RA8", "CENS", None),
        ("unifilar indirecta norma RA8 30/5 13200/120 trafo 700 kva circuito Magdalena", "RA8", "Magdalena"),
    ]:
        cfg = parse_spec(txt)[0]
        ok = cfg["norma"] == norma and (cto is None or cfg.get("circuito") == cto)
        malos += not ok
        print("OK  " if ok else "MAL ", f"norma={cfg['norma']} circuito={cfg.get('circuito')!r} | {txt}")
    try:   # ambiguedad real: sigue avisando
        parse_spec("indirecta CENS RA8 30/5 13200/120"); ok = False
    except ValueError:
        ok = True
    malos += not ok; print("OK  " if ok else "MAL ", "CENS + RA8 como normas -> sigue lanzando 'Norma ambigua'")

    # Avisos de coherencia: nada se descarta en silencio
    base = dict(DEFAULT, salida="unifilar", tipo="indirecta", instalacion="trafo",
                trafo_kva="700", rel_tc="30/5", rel_tp="13200/120")
    c, notas = bot._verificar_coherencia(dict(base, instalacion="", seccionador="antes"))
    ok = "seccionador" not in c and any("seccionador" in n.lower() for n in notas)
    malos += not ok; print("OK  " if ok else "MAL ", "antes sin trafo -> se quita y se avisa")
    c, notas = bot._verificar_coherencia(dict(base, n_trafos=2, trafo_kva_list=["500", "300"], seccionador="antes"))
    ok = any("celdas" in n for n in notas)
    malos += not ok; print("OK  " if ok else "MAL ", "multi-celda + seccionador -> se avisa")
    c, notas = bot._verificar_coherencia(dict(base, seccionador="antes", trafo_uso="exclusivo"))
    ok = not notas
    malos += not ok; print("OK  " if ok else "MAL ", "caso normal -> sin avisos", notas)

    # Render real de las dos posiciones (no debe lanzar y el PNG debe ser valido)
    for pos in ("antes", "despues"):
        imgs, _, _ = bot._generar(dict(base, trafo_uso="exclusivo", seccionador=pos))
        ok = bool(imgs) and os.path.getsize(imgs[0][1]) > 3000
        malos += not ok; print("OK  " if ok else "MAL ", f"render seccionador={pos}")

    print("\nRESULTADO:", "TODO OK" if not malos else f"{malos} fallos")
    return malos

if __name__ == "__main__":
    sys.exit(1 if main() else 0)
