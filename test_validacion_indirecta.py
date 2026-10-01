#!/usr/bin/env python3
"""Validacion numerica del punto de medida indirecta (In del trafo vs primario
del TC, primario del TP vs red) y su integracion con el bot.

Valores esperados calculados a mano:
  700 kVA @ 13,2 kV trifasico: In = 700 / (sqrt(3) * 13,2) = 30,62 A
  75 kVA monofasico @ 7,62 kV (TP 7620/120):  In = 75 / 7,62 = 9,84 A"""
import sys, os, logging, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
logging.disable(logging.CRITICAL)
import diagram_engine as de
import bot
from parser import DEFAULT

def cfg(**kw):
    base = dict(DEFAULT, tipo="indirecta", sistema="tri4h", instalacion="trafo", n_trafos=1,
                trafo_kva="700", v_mt="13.2 kV", rel_tc="50/5", rel_tp="13200/120", trafo_uso="exclusivo")
    base.update(kw); return base

def niveles(c): return [n for n, _, _ in de._validar_indirecta(c)]

def main():
    malos = 0
    def chk(ok, msg):
        nonlocal malos
        malos += not ok; print("OK  " if ok else "MAL ", msg)

    In, kv, est = de._corriente_nominal(cfg())
    chk(abs(In - 700 / (math.sqrt(3) * 13.2)) < 1e-6 and not est, f"In 700 kVA @ 13,2 kV = {In:.2f} A (30,62)")
    chk(niveles(cfg(rel_tc="50/5")) == ["ok", "ok"],      "TC 50/5 (61 %) y TP 13200/120 -> ok, ok")
    chk(niveles(cfg(rel_tc="30/5"))[0] == "warn",         "TC 30/5 (102 %) -> warn 'justo' (el caso del usuario)")
    chk(niveles(cfg(rel_tc="20/5"))[0] == "err",          "TC 20/5 (153 %) -> err subdimensionado")
    chk(niveles(cfg(rel_tc="400/5"))[0] == "warn",        "TC 400/5 (7,7 %) -> warn sobredimensionado")
    chk(niveles(cfg(rel_tp="34500/120")) [1] == "warn",   "TP 34500/120 con red de 13,2 kV -> warn")
    chk(niveles(cfg(rel_tp="7620/120"))[1] == "ok",       "TP 7620/120 (fase-neutro de 13,2 kV) -> ok")
    # sin v_mt: el kV se deduce del TP y se marca como estimado
    In2, kv2, est2 = de._corriente_nominal(cfg(v_mt="", rel_tp="7620/120"))
    chk(est2 and abs(kv2 - 13.2) < 1e-9, f"kV estimado desde TP 7620/120 trifasico -> {kv2} (13,2), estimado={est2}")
    In3, kv3, est3 = de._corriente_nominal(cfg(v_mt="", sistema="mono", trafo_kva="75", rel_tp="7620/120"))
    chk(est3 and abs(In3 - 75 / 7.62) < 1e-6, f"monofasico: In = {In3:.2f} A = 75/7,62 (sin sqrt(3) ni conversion)")
    # no aplica / faltan datos -> sin ruido
    chk(de._validar_indirecta(cfg(tipo="semidirecta")) == [], "semidirecta -> sin validacion")
    chk(de._validar_indirecta(cfg(n_trafos=3)) == [],         "multi-celda -> sin validacion")
    chk(de._validar_indirecta(cfg(trafo_kva="", rel_tp="")) == [], "sin kVA ni TP -> no inventa nada")
    try:
        r = de._validar_indirecta(cfg(rel_tc="abc", trafo_kva="x", rel_tp="??", n_trafos="z"))
        chk(isinstance(r, list), "datos basura -> devuelve lista, no truena")
    except Exception as e:
        chk(False, f"datos basura -> lanzo {type(e).__name__}: {e}")

    # El bot lo muestra como aviso solo cuando algo NO esta bien
    _, notas = bot._verificar_coherencia(cfg(rel_tc="30/5"))
    chk(any("justo" in n for n in notas), "bot: TC justo -> aviso en el caption")
    _, notas = bot._verificar_coherencia(cfg(rel_tc="50/5"))
    chk(not any("TC" in n for n in notas), "bot: TC correcto -> sin aviso")

    # Render real con error/aviso/ok (no debe lanzar)
    for rtc in ("20/5", "30/5", "50/5"):
        imgs, _, _ = bot._generar(cfg(rel_tc=rtc, salida="unifilar"))
        chk(os.path.getsize(imgs[0][1]) > 3000, f"render con TC {rtc}")
    # Seccionador abierto y cerrado
    for est_s in ("cerrado", "abierto"):
        imgs, _, _ = bot._generar(cfg(salida="unifilar", seccionador="antes", seccionador_estado=est_s))
        chk(os.path.getsize(imgs[0][1]) > 3000, f"render seccionador {est_s}")

    print("\nRESULTADO:", "TODO OK" if not malos else f"{malos} fallos")
    return malos

if __name__ == "__main__":
    sys.exit(1 if main() else 0)
