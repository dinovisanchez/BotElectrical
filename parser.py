# -*- coding: utf-8 -*-
"""Interpreta especificaciones de medida desde texto libre o argumentos key=value."""
import re

DEFAULT = dict(sistema="tri4h", tipo="indirecta", respaldo=False,
               norma="RA8", rel_tc="", rel_tp="", proyecto="", salida="conexiones", tension="")

def _norm(s):
    s = s.lower()
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u")]:
        s = s.replace(a, b)
    return s

def parse_spec(text):
    """Devuelve (cfg, entendido:list[str], faltante:list[str])."""
    cfg = dict(DEFAULT)
    t = _norm(text)
    entendido = []

    kv = dict(re.findall(r"(\w+)\s*=\s*([^\s]+)", t))
    if "tipo" in kv: t += " " + kv["tipo"]
    if "sistema" in kv: t += " " + kv["sistema"]
    if "norma" in kv: t += " " + kv["norma"]
    if kv.get("rtc"): cfg["rel_tc"] = kv["rtc"]; entendido.append(f"RTC {kv['rtc']}")
    if kv.get("rtp"): cfg["rel_tp"] = kv["rtp"]; entendido.append(f"RTP {kv['rtp']}")
    if kv.get("respaldo") in ("si","true","1","yes"): cfg["respaldo"] = True

    if "semidirect" in t: cfg["tipo"] = "semidirecta"
    elif "indirect" in t: cfg["tipo"] = "indirecta"
    elif "direct" in t: cfg["tipo"] = "directa"
    entendido.append(f"Tipo: {cfg['tipo']}")

    if "monofasic" in t or re.search(r"\bmono\b", t):
        cfg["sistema"] = "mono"
    elif "bifasic" in t or re.search(r"\bbi\b", t):
        cfg["sistema"] = "bifasico"
    elif "2 element" in t or "dos element" in t or "3 hilos" in t or "trifilar" in t or "aron" in t:
        cfg["sistema"] = "tri3h"
    elif "3 element" in t or "tres element" in t or "4 hilos" in t or "tetrafilar" in t or "trifasic" in t:
        cfg["sistema"] = "tri4h"
    sis_txt = {"mono":"monofasica","bifasico":"bifasica",
               "tri3h":"trifasica 3 hilos (2 elem.)","tri4h":"trifasica 4 hilos (3 elem.)"}
    entendido.append(f"Sistema: {sis_txt[cfg['sistema']]}")

    if "respaldo" in t or "chequeo" in t or "principal" in t or "2 medidor" in t or "dos medidor" in t:
        cfg["respaldo"] = True
        entendido.append("Con respaldo (principal + chequeo)")

    if "cens" in t: cfg["norma"] = "CENS"
    elif "ra8" in t or "ra-8" in t or "nacional" in t: cfg["norma"] = "RA8"
    entendido.append(f"Norma: {cfg['norma']}")

    if not cfg["rel_tc"] or not cfg["rel_tp"]:
        rels = re.findall(r"\b(\d{2,6})\s*/\s*(\d{1,4})\b", text)
        for a, b in rels:
            if int(b) in (1, 5):
                if not cfg["rel_tc"]: cfg["rel_tc"] = f"{a}/{b}"; entendido.append(f"RTC {a}/{b}")
            else:
                if not cfg["rel_tp"]: cfg["rel_tp"] = f"{a}/{b}"; entendido.append(f"RTP {a}/{b}")

    if "unifilar" in t or "unilineal" in t or "unilinear" in t:
        cfg["salida"] = "ambos" if ("conexion" in t or "ambos" in t or "los dos" in t) else "unifilar"
        entendido.append(f"Diagrama: {cfg['salida']}")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kv", t)
    if m: cfg["tension"] = m.group(1).replace(",", ".") + " kV"

    if "rele" in t or "proteccion" in t or "ansi" in t:
        cfg["rele"] = True
    if "sin pararrayos" in t or "sin dps" in t:
        cfg["dps"] = False
    elif "pararrayos" in t or "dps" in t:
        cfg["dps"] = True

    if ("transformador" in t or "trafo" in t) and ("unifilar" in t or "totalizador" in t or "kva" in t):
        cfg["unifilar_trafo"] = True
        cfg["salida"] = "unifilar"
        mk = re.search(r"(\d+(?:[.,]\d+)?)\s*kva", t)
        if mk: cfg["trafo_kva"] = mk.group(1).replace(",", ".")
        if "bifasic" in t: cfg["trafo_tipo"] = "bifasico"
        elif "monofasic" in t: cfg["trafo_tipo"] = "monofasico"
        elif "trifasic" in t: cfg["trafo_tipo"] = "trifasico"
        mcc = re.search(r"(\d+)\s*cortacircuit", t)
        if mcc: cfg["n_cc"] = int(mcc.group(1))
        mtc = re.search(r"(\d+)\s*tc", t)
        if mtc: cfg["n_tc"] = int(mtc.group(1))
        ma = re.search(r"(\d+)\s*a(?:mp|mps|mperios)?\b", t)
        if ma: cfg["interruptor"] = ma.group(1) + " A"

    faltante = []
    if cfg["tipo"] == "indirecta" and not cfg["rel_tc"]:
        faltante.append("relacion de TC (ej. 200/5)")
    if cfg["tipo"] == "indirecta" and not cfg["rel_tp"]:
        faltante.append("relacion de TP (ej. 13200/120)")
    return cfg, entendido, faltante


if __name__ == "__main__":
    tests = [
        "diagrama indirecta trifasica 3 elementos norma CENS rtc 200/5 rtp 13200/120",
        "semidirecta 3 elementos 300/5 norma ra8",
        "indirecta 2 elementos aron con respaldo 100/5 7620/120",
        "medida monofasica directa",
        "tipo=indirecta sistema=tri4h norma=RA8 rtc=200/5 rtp=13200/120 respaldo=si",
    ]
    for x in tests:
        cfg, ent, falt = parse_spec(x)
        print("IN :", x)
        print("CFG:", cfg)
        print("FAL:", falt, "\n")
