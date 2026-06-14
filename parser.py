# -*- coding: utf-8 -*-
"""Interpreta especificaciones de medida desde texto libre o argumentos key=value."""
import re

DEFAULT = dict(sistema="tri4h", tipo="indirecta", respaldo=False,
               norma="RA8", rel_tc="", rel_tp="", proyecto="", salida="conexiones", tension="",
               asimetrico=False,
               trafo_presente=False,
               interruptor_pos=None,   # G5: era "antes", forzaba elemento falso en diagramas
               interruptor_antes_kva="", interruptor_despues_kva="")

def _norm(s):
    """Normaliza: lowercase + sin acentos."""
    s = s.lower()
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),
                  ("à","a"),("è","e"),("ì","i"),("ò","o"),("ù","u")]:
        s = s.replace(a, b)
    return s

def parse_spec(text):
    """
    Devuelve (cfg, entendido:list[str], faltante:list[str]).
    Lanza ValueError si especificacion es muy ambigua o inconsistente.
    """
    if not text or not isinstance(text, str):
        raise ValueError("Especificacion vacia o invalida")

    cfg = dict(DEFAULT)
    t = _norm(text)
    entendido = []

    # --- Parsear key=value pairs primero ---
    kv = dict(re.findall(r"(\w+)\s*=\s*([^\s]+)", t))
    if "tipo" in kv: t += " " + kv["tipo"]
    if "sistema" in kv: t += " " + kv["sistema"]
    if "norma" in kv: t += " " + kv["norma"]
    if kv.get("rtc"):
        cfg["rel_tc"] = kv["rtc"]
        entendido.append(f"RTC {kv['rtc']}")
    if kv.get("rtp"):
        cfg["rel_tp"] = kv["rtp"]
        entendido.append(f"RTP {kv['rtp']}")
    if kv.get("respaldo") in ("si","true","1","yes"):
        cfg["respaldo"] = True

    # --- TIPO ---
    tipo_count = 0
    if re.search(r"\bdirecta\b", t) and not re.search(r"(semi|indirect)", t):
        cfg["tipo"] = "directa"
        tipo_count += 1
    if re.search(r"semidirect", t):
        cfg["tipo"] = "semidirecta"
        tipo_count += 1
    if re.search(r"indirect", t):
        cfg["tipo"] = "indirecta"
        tipo_count += 1

    if tipo_count > 1:
        raise ValueError("Tipo ambiguo. Especifica UNO: directa, semidirecta, indirecta")

    entendido.append(f"Tipo: {cfg['tipo']}")

    # --- SISTEMA ---
    # G3: patrones específicos ("3 hilos", "4 hilos", "aron") tienen prioridad
    # sobre el genérico "trifasic" para evitar ambigüedad en "trifasica 3 hilos".
    tri3h_especificos = ["2 element", "dos element", "3 hilos", "trifilar", "aron"]
    tri4h_especificos = ["3 element", "tres element", "4 hilos", "tetrafilar"]

    tiene_tri3h = any(p in t for p in tri3h_especificos)
    tiene_tri4h = any(p in t for p in tri4h_especificos) or \
                  ("trifasic" in t and not tiene_tri3h)

    detected_sistemas = []
    if any(p in t for p in ["monofasic", "mono"]): detected_sistemas.append("mono")
    if any(p in t for p in ["bifasic", "bi"]):      detected_sistemas.append("bifasico")
    if tiene_tri3h: detected_sistemas.append("tri3h")
    if tiene_tri4h: detected_sistemas.append("tri4h")

    if len(detected_sistemas) > 1:
        raise ValueError(f"Sistema ambiguo: {detected_sistemas}. Especifica UNO: mono, bifasico, tri3h, tri4h")
    elif detected_sistemas:
        cfg["sistema"] = detected_sistemas[0]

    sis_txt = {"mono":"monofasica","bifasico":"bifasica",
               "tri3h":"trifasica 3 hilos (2 elem.)","tri4h":"trifasica 4 hilos (3 elem.)"}
    entendido.append(f"Sistema: {sis_txt[cfg['sistema']]}")

    # --- RESPALDO ---
    if any(x in t for x in ["respaldo", "chequeo", "principal", "2 medidor", "dos medidor"]):
        cfg["respaldo"] = True
        entendido.append("Con respaldo (principal + chequeo)")

    # --- NORMA ---
    norma_count = sum(1 for x in ["cens", "ra8", "ra-8"] if x in t)
    if norma_count > 1:
        raise ValueError("Norma ambigua: especifica CENS o RA8")

    if "cens" in t:
        cfg["norma"] = "CENS"
    elif "ra8" in t or "ra-8" in t or "nacional" in t:
        cfg["norma"] = "RA8"
    entendido.append(f"Norma: {cfg['norma']}")

    # --- RELACIONES TC/TP ---
    if not cfg["rel_tc"] or not cfg["rel_tp"]:
        rels = re.findall(r"\b(\d{2,6})\s*/\s*(\d{1,4})\b", text)
        for a, b in rels:
            try:
                b_int = int(b)
                if b_int in (1, 5):
                    if not cfg["rel_tc"]:
                        cfg["rel_tc"] = f"{a}/{b}"
                        entendido.append(f"RTC {a}/{b}")
                elif b_int in (100, 110, 120, 230, 240):
                    if not cfg["rel_tp"]:
                        cfg["rel_tp"] = f"{a}/{b}"
                        entendido.append(f"RTP {a}/{b}")
            except Exception:
                pass

    # --- DIAGRAMA ---
    if "unifilar" in t or "unilineal" in t or "unilinear" in t:
        cfg["salida"] = "ambos" if ("conexion" in t or "ambos" in t or "los dos" in t) else "unifilar"
        entendido.append(f"Diagrama: {cfg['salida']}")

    # --- TENSION ---
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kv", t)
    if m:
        cfg["tension"] = m.group(1).replace(",", ".") + " kV"

    # --- PROTECCIONES ---
    if "rele" in t or "proteccion" in t or "ansi" in t:
        cfg["rele"] = True
    if "sin pararrayos" in t or "sin dps" in t:
        cfg["dps"] = False
    elif "pararrayos" in t or "dps" in t:
        cfg["dps"] = True

    # --- TRANSFORMADOR (trafo en MT) ---
    if any(x in t for x in ["transformador", "trafo"]) and any(x in t for x in ["unifilar", "totalizador", "kva"]):
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

    # --- VALIDAR FALTANTE ---
    faltante = []
    if cfg["tipo"] == "indirecta" and not cfg["rel_tc"]:
        faltante.append("relacion de TC (ej. 200/5)")
    if cfg["tipo"] == "indirecta" and not cfg["rel_tp"]:
        faltante.append("relacion de TP (ej. 13200/120)")
    # M4: semidirecta tambien necesita RTC para etiquetar correctamente el diagrama
    if cfg["tipo"] == "semidirecta" and not cfg["rel_tc"]:
        faltante.append("relacion de TC (ej. 200/5)")

    return cfg, entendido, faltante


if __name__ == "__main__":
    tests = [
        "diagrama indirecta trifasica 3 elementos norma CENS rtc 200/5 rtp 13200/120",
        "semidirecta 3 elementos norma RA8 300/5",
        "indirecta 2 elementos aron 100/5 7620/120",
        "medida monofasica directa",
        "tipo=indirecta sistema=tri4h norma=RA8 rtc=200/5 rtp=13200/120 respaldo=si",
        # G3: estos dos casos deben resolverse sin ambiguedad
        "trifasica 3 hilos indirecta CENS 200/5 13200/120",
        "trifasica 4 hilos semidirecta RA8 300/5",
    ]
    for x in tests:
        try:
            cfg, ent, falt = parse_spec(x)
            print(f"IN : {x}")
            print(f"CFG: tipo={cfg['tipo']} sistema={cfg['sistema']} norma={cfg['norma']}")
            print(f"FAL: {falt}\n")
        except ValueError as e:
            print(f"IN : {x}")
            print(f"ERR: {e}\n")
