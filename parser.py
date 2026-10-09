# -*- coding: utf-8 -*-
"""Interpreta especificaciones de medida desde texto libre o argumentos key=value."""
import re

DEFAULT = dict(sistema="tri4h", tipo="indirecta", respaldo=False,
               norma="RA8", rel_tc="", rel_tp="", proyecto="", salida="conexiones", tension="",
               conexion="simetrica",
               trafo_uso="",           # "exclusivo" | "compartido" | "" (sin especificar)
               trafo_n_usuarios="",    # cantidad de otros usuarios (solo si compartido)
               trafo_gabinete=None)    # True=gabinete/cuarto cerrado, False=red abierta, None=sin especificar

def _norm(s):
    """Normaliza: lowercase + sin acentos."""
    s = s.lower()
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),
                  ("à","a"),("è","e"),("ì","i"),("ò","o"),("ù","u")]:
        s = s.replace(a, b)
    return s

_NUM_PAL = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
            "seis": 6, "siete": 7, "ocho": 8}
_ORD_PAL = {"primer": 0, "primero": 0, "primera": 0, "segundo": 1, "segunda": 1, "tercer": 2,
            "tercero": 2, "tercera": 2, "cuarto": 3, "cuarta": 3, "ultimo": -1, "ultima": -1}
# lista de kVA: "300 kva", "300 y 150 kva", "300, 150 kva", "300 + 150 kva"
_KVA_LISTA = r"(\d+(?:[.,]\d+)?(?:\s*(?:,|\by\b|\be\b|\+)\s*\d+(?:[.,]\d+)?)*)\s*kva\b"
_PLANTA_RE = (r"planta\s+(?:de\s+)?(?:respaldo|emergencia|electrica|generadora)|generador"
              r"|grupo\s+electrogeno|planta\s+(?:de\s+)?\d+(?:[.,]\d+)?\s*kva")
_FIN_CLAUSULA = r"[,;]|\.(?:\s|$)|\s+y\s+"


def _extraer_planta(t, cfg, entendido):
    """Planta de respaldo (generador): es OTRA cosa que el medidor de respaldo. Se quita su
    clausula del texto para que no dispare `respaldo` ni aporte su kVA al trafo. Devuelve t."""
    neg = re.search(r"\b(?:sin|no\s+(?:hay|tiene|existe|se\s+encontro))\s+(?:una\s+|ninguna\s+)?"
                    r"(?:planta|generador|grupo\s+electrogeno)(?:\s+de\s+(?:respaldo|emergencia))?", t)
    if neg:
        cfg["planta_respaldo"] = {"existe": False, "kva": None, "transferencia": None}
        entendido.append("Sin planta de respaldo")
        return t[:neg.start()] + " " + t[neg.end():]
    m = re.search(r"\b(?:" + _PLANTA_RE + r")\b", t)
    if not m:
        return t
    fin = re.search(_FIN_CLAUSULA, t[m.end():])
    fin = m.end() + (fin.start() if fin else len(t) - m.end())
    clausula = t[m.start():fin]
    mk = re.search(r"(\d+(?:[.,]\d+)?)\s*kva", clausula)
    kva = mk.group(1).replace(",", ".") if mk else None
    # la transferencia suele ir despues de una coma: se busca en todo el texto
    mt = re.search(r"\btransferencia\s+(automatica|manual)\b", t) or re.search(r"\b(automatica|manual)\b", clausula)
    transf = mt.group(1) if mt else ("automatica" if re.search(r"\bats\b", t) else None)
    cfg["planta_respaldo"] = {"existe": True, "kva": kva, "transferencia": transf}
    entendido.append("Planta de respaldo" + (f" {kva} kVA" if kva else "")
                     + (f", transferencia {transf}" if transf else ""))
    t = t[:m.start()] + " " + t[fin:]
    return re.sub(r"\btransferencia\s+(?:automatica|manual)\b|\bats\b", " ", t)


# Fase del TRANSFORMADOR dicha junto a su nombre ("transformador trifasico", "trafo de 150 kVA trifasico",
# "el transformador es trifasico"). Es independiente del sistema de la MEDIDA: un transformador trifasico
# puede alimentar un medidor monofasico o bifasico.
_FASE_PAL = {"mono": "monofasico", "bi": "bifasico", "tri": "trifasico"}
_TRAFO_RELLENO = (r"(?:de|tipo|es|sera|seria|interno|interior|externo|exterior|compartido|exclusivo|propio|"
                  r"privado|seco|nuevo|existente|distribucion|potencia|poste|pedestal|aceite|en|del|usuario|el|la)")
_RE_FASE_TRAFO = re.compile(
    r"\b(?:transformador(?:es)?|trafos?|trf)(?:\s+" + _TRAFO_RELLENO + r"){0,3}"
    r"(?:\s+(?:de\s+)?\d+(?:[.,]\d+)?\s*kva)?(?:\s+es)?\s+(mono|bi|tri)fasic\w*")

def _fase_trafo(t):
    """(t sin la fase del transformador, 'monofasico'|'bifasico'|'trifasico'|''). La fase dicha junto a
    'transformador'/'trafo' se saca del texto para que NO cuente como el sistema de la medida
    ('transformador trifasico, medida bifasica' ya no es un 'Sistema ambiguo')."""
    fases = []
    def _quita(m):
        fases.append(_FASE_PAL[m.group(1)])
        return m.string[m.start():m.start(1)].rstrip()
    t2 = _RE_FASE_TRAFO.sub(_quita, t)
    return t2, (fases[0] if fases else "")


def _sistemas_dichos(t):
    """Sistemas de la MEDIDA que menciona `t` (texto normalizado y SIN la fase del trafo):
    lista de 'mono' | 'bifasico' | 'tri3h' | 'tri4h' (vacia = no dijo; 2+ = ambiguo)."""
    # G3: patrones específicos ("3 hilos", "4 hilos", "aron") tienen prioridad
    # sobre el genérico "trifasic" para evitar ambigüedad en "trifasica 3 hilos".
    tri3h_especificos = ["2 element", "dos element", "3 hilos", "trifilar", "aron"]
    tri4h_especificos = ["3 element", "tres element", "4 hilos", "tetrafilar"]
    # "bifasica 3 hilos" / "monofasica 3 hilos" son sistemas bifasico/monofasico, no trifasico de 3 hilos
    bi_mono = bool(re.search(r"bifasic|monofasic|\b(?:mono|bi)\b", t)) and "trifasic" not in t
    tiene_tri3h = any(p in t for p in tri3h_especificos if not (p == "3 hilos" and bi_mono))
    tiene_tri4h = any(p in t for p in tri4h_especificos) or \
                  ("trifasic" in t and not tiene_tri3h)
    dicho = []
    if "monofasic" in t or re.search(r"\bmono\b", t): dicho.append("mono")
    if "bifasic" in t or re.search(r"\bbi\b", t):      dicho.append("bifasico")
    if tiene_tri3h: dicho.append("tri3h")
    if tiene_tri4h: dicho.append("tri4h")
    return dicho


def fases_dichas(text):
    """(sistema de la medida | None, fase del transformador | None) tal como el usuario las DIJO en `text`
    (None = no lo dijo o es ambiguo). Sin excepciones: lo usa el bot para no perder 'trafo trifasico,
    medida bifasica' cuando el modelo de IA confunde las dos."""
    try:
        t, ft = _fase_trafo(_norm(text or ""))
        dicho = _sistemas_dichos(t)
        return (dicho[0] if len(dicho) == 1 else None), (ft or None)
    except Exception:
        return None, None



def _extraer_trafos(t, cfg, entendido, faltante):
    """2+ transformadores (cantidad / lista de kVA / 'trafo 1 de 300 kVA, trafo 2 de 150 kVA'),
    configuracion (paralelo / independientes) y cual es el compartido. Solo actua con 2 o mas."""
    n = None
    # (el numero no puede ser el denominador de una relacion: "200/5 trafo 300 kVA" no son 5 trafos)
    m_n = re.search(r"(?<![/.,\d])\b(\d+|" + "|".join(_NUM_PAL) + r")\s+(?:transformadores|trafos|transformador|trafo)\b", t)
    if m_n:
        n = int(m_n.group(1)) if m_n.group(1).isdigit() else _NUM_PAL[m_n.group(1)]
    indexados = {int(i): k.replace(",", ".") for i, k in re.findall(
        r"\b(?:trafo|transformador|trf)\s*#?(\d)\s*(?:de|:|=|-)?\s*(\d+(?:[.,]\d+)?)\s*kva", t)}
    vals = []
    mk = re.search(_KVA_LISTA, t)
    if mk:
        vals = [v.replace(",", ".") for v in re.findall(r"\d+(?:[.,]\d+)?", mk.group(1))]
    todos_kva = [v.replace(",", ".") for v in re.findall(r"(\d+(?:[.,]\d+)?)\s*kva", t)]
    if len(vals) < 2 and len(todos_kva) >= 2:      # "300 kVA y 150 kVA" (unidad repetida)
        vals = todos_kva
    plural = re.search(r"\b(?:transformadores|trafos)\b", t)
    if len(indexados) >= 2:
        n = max(indexados)
        lista = [indexados.get(i + 1) for i in range(n)]
    elif n is not None and n >= 2:
        lista = vals if (len(vals) == n) else vals * n if len(vals) == 1 else vals if len(vals) >= 2 else [None] * n
        n = len(lista)
    elif n is None and plural and len(vals) >= 2:
        lista = vals; n = len(vals)
    else:
        return
    n = min(n, 12); lista = lista[:n]

    tipo = cfg.get("trafo_tipo", "")
    uso = [""] * n
    if "compartido" in t:
        uso = ["exclusivo"] * n
        idx = None
        m_num = re.search(r"\b(?:trafo|transformador|trf)\s*#?(\d)\s*(?:es\s+)?compartid", t)
        m_ord = re.search(r"\b(primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|ultim[oa])\s+(?:trafo\s+|transformador\s+)?(?:es\s+)?compartid", t)
        m_uno = re.search(r"\b(?:uno|una)\s+(?:de\s+(?:ellos|ellas|los\s+\w+)\s+)?(?:es\s+|sea\s+|esta\s+)?compartid", t)
        if m_num:   idx = int(m_num.group(1)) - 1
        elif m_ord: idx = _ORD_PAL[m_ord.group(1)]
        elif m_uno:
            idx = n - 1
            entendido.append(f"Compartido: TRF{n} (no dijiste cual; supuse el ultimo)")
        if idx is not None:
            idx = idx if idx >= 0 else n + idx
            if 0 <= idx < n:
                uso[idx] = "compartido"
            else:
                uso = ["compartido"] * n
        else:
            uso = ["compartido"] * n
            entendido.append("Todos los transformadores compartidos (no dijiste cual)")
    elif re.search(r"\b(?:exclusivo|propio|privado)\b", t):
        uso = ["exclusivo"] * n

    cfg["transformadores"] = [{"kva": lista[i] or "", "tipo": tipo, "uso": uso[i]} for i in range(n)]
    cfg["instalacion"] = "trafo"
    cfg["n_trafos"] = n
    cfg.pop("trafo_kva", None)
    cfg["trafo_kva_list"] = [k for k in lista] if all(lista) else []
    if "compartido" in uso:
        cfg["trafo_uso"] = "compartido"
    elif "exclusivo" in uso:
        cfg["trafo_uso"] = "exclusivo"
    if re.search(r"\bindependiente|\bseparad[oa]s?\b|\bcada\s+un[oa]\s+con\s+su\b", t):
        cfg["configuracion_transformadores"] = "independientes"
    elif re.search(r"\bparalelo\b", t):
        cfg["configuracion_transformadores"] = "paralelo"
    conf = cfg.get("configuracion_transformadores") or "paralelo (por defecto)"
    entendido.append(f"{n} transformadores: " + (" + ".join(k for k in lista if k) + " kVA" if any(lista) else "kVA sin indicar")
                     + f" · {conf}")
    if not all(lista):
        faltante.append("kVA de cada transformador (ej. 300 kVA cada uno)")


def _extraer_vmt(t):
    """Tension de MEDIA TENSION en kV como texto ('13.2', '34.5') o None. `t` va en minusculas y sin tildes.
    Entiende: '13.2 kV', '13,2kv', '13200 V', '13.200 voltios', '13200 volts', 'media tension 13,2',
    'tension media de 34.5', 'MT 13200', 'alta tension 13.2'. No toca relaciones de TP ('13200/120') ni
    tensiones de BT (220 V) ni potencias ('75 kVA')."""
    def kv(txt):
        v = float(txt.replace(",", "."))
        return v
    def fmt(v):
        return f"{v:g}"
    m = re.search(r"(?<![/\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:kv|kilovoltios?|kilovolts?)(?!a)\b", t)
    if m:
        return m.group(1).replace(",", ".")
    # 13200 V / 13.200 V / 13 200 V (miles): solo si pasa de 1000 V y no es parte de una relacion X/Y
    m = re.search(r"(?<![/\d.,])(\d{1,3}(?:[.,\s]\d{3})+|\d{4,6})\s*(?:v\b|voltios?|volts?)(?!\s*[/a])", t)
    if m and not re.match(r"\s*/", t[m.end():]):
        v = float(re.sub(r"[.,\s]", "", m.group(1)))
        if 1000 <= v <= 230000:
            return fmt(v / 1000)
    # tras la palabra "media tension" / "MT": 'tension media 13,2', 'MT 13200', 'MT de 34.5'
    m = re.search(r"(?:media\s+tension|tension\s+media|alta\s+tension|\bmt\b)\s*(?:de|a|en|es|:|=)?\s*"
                  r"(\d{1,3}(?:[.,]\d{1,2})?|\d{1,3}[.,]\d{3}|\d{4,6})\b(?!\s*(?:/|a\b|amp|hilos?|kva|va\b|medidor|usuario|polos?|p\b|%|mm))", t)
    if m:
        txt = m.group(1)
        v = float(re.sub(r"[.,](?=\d{3}\b)", "", txt).replace(",", ".")) if re.fullmatch(r"\d{1,3}[.,]\d{3}", txt) else kv(txt)
        if v >= 1000: v /= 1000.0
        if 1.0 < v <= 69.0:                      # sin unidad solo vale un valor de MT (13.2, 34.5...), no 220
            return fmt(v)
    return None


def _extraer_acta(t, text, cfg, entendido):
    """Ubicacion de la medida (BT/MT) y celda de medida."""
    m = re.search(r"\b(?:medida|medicion|medidor)\s+(?:en|al|del)\s+(?:el\s+)?(?:lado\s+(?:de\s+)?)?"
                  r"(mt|media\s+tension|alta|bt|baja\s+tension|baja)\b", t)
    if m:
        cfg["ubicacion_medida"] = "MT" if m.group(1) in ("mt", "alta") or m.group(1).startswith("media") else "BT"
        entendido.append(f"Medida en {cfg['ubicacion_medida']}")
    if re.search(r"\bsin\s+celda\b|\bno\s+(?:esta|hay|tiene)\s+(?:en\s+)?celda\b", t):
        cfg["celda_medida"] = {"existe": False, "tipo": "", "estado": ""}
        entendido.append("Sin celda de medida")
    elif re.search(r"\bcelda\b", t):
        mt = re.search(r"\bcelda(?:\s+de\s+(?:medida|medicion))?\s+(?:tipo\s+)?([a-z]{1,3}\s?-?\d{2,4})\b", text, re.I)
        me = re.search(r"\bestado(?:\s+de\s+(?:la\s+)?celda)?\s*(?:es\s+|:)?\s*"
                       r"(bueno|regular|malo|deficiente|excelente|aceptable|bien|mal)\b", t)
        tipo = re.sub(r"[\s-]", "", mt.group(1)).upper() if mt else ""
        estado = me.group(1).capitalize() if me else ""
        cfg["celda_medida"] = {"existe": True, "tipo": tipo, "estado": estado}
        entendido.append("Celda de medida" + (f" {tipo}" if tipo else "") + (f", estado {estado}" if estado else ""))


def _extraer_gabinete(t, text, cfg, entendido, tipo_count):
    """Datos del plano de GABINETE COMPARTIDO (medida directa con otros usuarios): cuantos
    medidores/usuarios comparten el punto, interior/red abierta, ubicacion del trafo, totalizador
    (antes/despues del medidor), tension BT, bajante MT y clase del medidor. Solo rellena lo que el
    texto dice; nada se inventa."""
    comparte = bool(re.search(r"compartid|gabinete|varios\s+usuarios|otros\s+usuarios", t))
    # --- cuantos otros usuarios / medidores ---
    # "otros" = medidores de OTROS usuarios (sin contar el de esta medida); el total es otros + 1.
    # Frases: "4 medidores mas", "con 8 mas", "otros 8", "compartido con 8" (-> 8 otros), "compartido entre 9" /
    # "somos 9" / "5 medidores en total" / "gabinete de 5 medidores" (-> total, 1 menos). No se confunde "con 8"
    # con una unidad ("compartido con 4 hilos", "con 100 A").
    if comparte and not cfg.get("trafo_n_usuarios"):
        otros, de_total = None, False
        unidad = r"(?!\s*(?:kva|kv|va?\b|a\b|amp|hilos?|polos?|p\b|fases?|f\b|awg|mm))"
        sust = r"(?:usuarios?|medidores?|clientes?|suscriptores?|apartamentos?|locales?|casas?|unidades?)"
        for pat, total in (
                (r"(\d+)\s+" + sust + r"\s+(?:mas|adicionales|extra|otros)\b", False),
                (r"\bcon\s+(\d+)\s+(?:mas|otros|otras|adicionales)\b", False),
                (r"(\d+)\s+(?:otros|otras|demas)\s+" + sust, False),
                (r"\b(?:con\s+)?otros\s+(\d+)\b" + unidad, False),
                (r"\b(?:somos|son)\s+(\d+)\b" + unidad, True),
                (r"(\d+)\s+" + sust + r"\s+en\s+total", True),
                (r"\ben\s+total\s+(\d+)\b" + unidad, True),
                (r"\bcompartid\w*\s+(?:entre|por)\s+(\d+)\b" + unidad, True),
                (r"\bcompartid\w*\s+con\s+(\d+)\b" + unidad, False),
                (r"\bcompart\w+\s+con\s+(\d+)\b" + unidad, False),
                (r"\b(\d+)\s+usuarios?\b", False),
                (r"\b(?:gabinete|punto|barraje|cuarto)\s+(?:de|con)\s+(\d+)\s+" + sust + r"\b(?!\s*(?:principal|de\s+respaldo|de\s+chequeo))", True),
                (r"\b(\d+)\s+medidores?\b(?!\s*(?:principal|de\s+respaldo|de\s+chequeo))", True)):
            m = re.search(pat, t)
            if m and int(m.group(1)) >= (2 if total else 1):
                otros, de_total = int(m.group(1)) - (1 if total else 0), total
                break
        if otros is not None and 0 < otros <= 99:
            cfg["trafo_n_usuarios"] = str(otros)
            if cfg.get("trafo_uso") != "compartido":
                cfg["trafo_uso"] = "compartido"
            entendido.append(f"Punto compartido: {otros} otros usuarios ({otros + 1} medidores en total)")
    if cfg.get("trafo_uso") == "compartido" and tipo_count == 0 and cfg.get("tipo") != "directa":
        cfg["tipo"] = "directa"
        entendido.append("Punto compartido -> tipo DIRECTA (cada usuario con medidor propio)")
    # --- gabinete interior / red abierta ---
    if cfg.get("trafo_uso") == "compartido" and cfg.get("trafo_gabinete") is None:
        if re.search(r"gabinete|cuarto\s+de\s+medidor|cuarto\s+electrico|encerrado|\binterior\b|interna|interno", t):
            cfg["trafo_gabinete"] = True
        elif re.search(r"red\s+abierta|intemperie|\bposte\b|aerea|aereo", t):
            cfg["trafo_gabinete"] = False
    # --- un punto compartido alimentado "en media tension" / subestacion / trafo tiene transformador ---
    if cfg.get("trafo_uso") == "compartido" and not cfg.get("instalacion") and (
            cfg.get("v_mt") or re.search(r"media\s+tension|\bmt\b|subestacion|transformador|\btrafo\b", t)):
        cfg["instalacion"] = "trafo"
    # --- ubicacion del transformador ---
    if re.search(r"(?:subestacion|transformador|trafo)\s+(?:interior|interna|interno)|(?:interior|interna|interno)\s+en\s+subestacion|cuarto\s+de\s+transformador", t):
        cfg["ubicacion_trafo"] = "interior"
    elif re.search(r"(?:transformador|trafo)\s+(?:en|de)\s+poste|poste\s+(?:con|de)\s+transformador|(?:transformador|trafo)\s+aereo", t):
        cfg["ubicacion_trafo"] = "poste"
    elif re.search(r"subestacion\s+(?:exterior|externa|intemperie|capsulada|pedestal)|(?:transformador|trafo)\s+(?:tipo\s+)?pedestal", t):
        cfg["ubicacion_trafo"] = "exterior"
    elif re.search(r"camara\s+(?:subterranea|de\s+transformador)|subestacion\s+subterranea", t):
        cfg["ubicacion_trafo"] = "camara"
    if cfg.get("ubicacion_trafo"):
        entendido.append("Ubicacion del trafo: " + cfg["ubicacion_trafo"])
        if cfg.get("trafo_uso") == "compartido" and not cfg.get("instalacion"):
            cfg["instalacion"] = "trafo"
    # --- totalizador (interruptor general del ramal) respecto al medidor ---
    if re.search(r"totalizador", t):
        if re.search(r"totalizador[^.;]{0,40}?(?:antes|anterior|aguas\s+arriba|previo)", t):
            cfg["totalizador"] = "antes"
        else:
            cfg["totalizador"] = "despues"        # "posterior al medidor", "despues", o sin posicion (lo habitual)
        entendido.append("Totalizador " + ("antes" if cfg["totalizador"] == "antes" else "despues") + " del medidor")
        ma = re.search(r"totalizador[^.;]{0,40}?(\d+)\s*a(?:mp|mps|mperios)?\b", t)
        if ma:
            cfg["proteccion_antes" if cfg["totalizador"] == "antes" else "proteccion_despues"] = ma.group(1) + " A"
        mp = re.search(r"totalizador[^.;]{0,40}?\b([1-4])\s*(?:p\b|polos)", t)
        if mp: cfg["interruptor_polos"] = mp.group(1)
        if re.search(r"totalizador[^.;]{0,40}?caja\s+moldeada", t): cfg["interruptor_tipo"] = "caja moldeada"
        elif re.search(r"totalizador[^.;]{0,40}?termomagnetic", t): cfg["interruptor_tipo"] = "termomagnetico"
    # --- posicion de ESTE medidor en el gabinete, de izquierda a derecha ("mi medida es la 3", "posicion 3") ---
    if comparte:
        mp_ = (re.search(r"\bposicion\s*(?:n[o°º.]?\s*)?(\d{1,2})\b", t)
               or re.search(r"\b(?:mi\s+(?:medida|medidor)|este\s+medidor|la\s+medida\s+objeto)\s+(?:es|esta\s+en|va\s+en)\s+"
                            r"(?:la\s+|el\s+)?(?:posicion\s+)?(?:n[o°º.]?\s*)?(\d{1,2})\b", t))
        if mp_ and 1 <= int(mp_.group(1)) <= 99:
            cfg["posicion_medida"] = mp_.group(1)
            entendido.append(f"Posicion de este medidor en el gabinete: {mp_.group(1)} (de izquierda a derecha)")
    # --- tension BT (ej. 220 V, 208/120 V); no confundir con 13200/120 (TP) ni con kV ---
    mb = re.search(r"(?<![/\d.,])(\d{3}(?:\s*/\s*\d{2,3})?)\s*(?:v|voltios?)\b(?!a)", t)
    if mb and not cfg.get("tension_bt"):
        cfg["tension_bt"] = re.sub(r"\s+", "", mb.group(1))
        entendido.append(f"Tension BT {cfg['tension_bt']} V")
    # --- bajante MT y clase del medidor ---
    mj = re.search(r"\bbajante\s*(?:en|de)?\s*([^,;\n.]{3,45})", text, re.IGNORECASE)
    if mj:
        cfg["bajante_mt"] = mj.group(1).strip()
        entendido.append("Bajante MT: " + cfg["bajante_mt"])
    mc = re.search(r"\bclase\s*(\d+(?:[.,]\d+)?\s*s?)\b", t)
    if mc and ("medidor" in t or "medida" in t):
        cfg["clase_medidor"] = mc.group(1).replace(" ", "").replace(".", ",").upper()
        entendido.append("Clase del medidor " + cfg["clase_medidor"])


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
    # La fase del TRANSFORMADOR no es el sistema de la MEDIDA ("transformador trifasico, medida bifasica"):
    # se separa antes de buscar el sistema (y por eso queda fuera de t, que es lo que se analiza).
    t, fase_trafo = _fase_trafo(t)
    if fase_trafo:
        cfg["trafo_tipo"] = fase_trafo
        entendido.append(f"Transformador {fase_trafo}")
    detected_sistemas = _sistemas_dichos(t)

    if len(detected_sistemas) > 1:
        raise ValueError(f"Sistema ambiguo: {detected_sistemas}. Especifica UNO: mono, bifasico, tri3h, tri4h")
    elif detected_sistemas:
        cfg["sistema"] = detected_sistemas[0]
    elif fase_trafo:                       # solo se dijo la fase del trafo: la medida sigue esa fase
        cfg["sistema"] = {"monofasico": "mono", "bifasico": "bifasico", "trifasico": "tri4h"}[fase_trafo]

    sis_txt = {"mono":"monofasica","bifasico":"bifasica",
               "tri3h":"trifasica 3 hilos (2 elem.)","tri4h":"trifasica 4 hilos (3 elem.)"}
    entendido.append(f"Sistema: {sis_txt[cfg['sistema']]}")

    # --- PLANTA DE RESPALDO (generador): distinta del medidor de respaldo ---
    t = _extraer_planta(t, cfg, entendido)

    # --- RESPALDO ---
    # (antes: "principal" a secas y "2 medidor" -- que tambien estaba dentro de "12 medidores" -- activaban el
    #  segundo medidor sin que nadie lo pidiera: "totalizador principal", "gabinete de 12 medidores")
    if (any(x in t for x in ["respaldo", "chequeo"])
            or re.search(r"medidor\s+principal|principal\s+y\s+(?:de\s+)?(?:respaldo|chequeo)", t)
            or (re.search(r"(?<!\d)(?:2|dos)\s+medidores", t) and not re.search(r"gabinete|compartid|usuarios", t))):
        cfg["respaldo"] = True
        entendido.append("Con respaldo (principal + respaldo)")

    # --- NORMA ---
    # El NOMBRE de un circuito o de un punto de conexion puede ser "RA8" (asi se
    # llama en algunos operadores, p.ej. "circuito RA8"): no es la norma. Se
    # quita de t ANTES de buscar la norma, o "circuito RA8 ... CENS" lanzaba
    # "Norma ambigua".
    t_norma = re.sub(r"\b(?:circuito|cto|punto\s+de\s+conexion)\s*:?\s*[a-z0-9\-]+", " ", t)
    norma_count = sum(1 for x in ["cens", "ra8", "ra-8"] if x in t_norma)
    if norma_count > 1:
        raise ValueError("Norma ambigua: especifica CENS o RA8")

    if "cens" in t_norma:
        cfg["norma"] = "CENS"
    elif "ra8" in t_norma or "ra-8" in t_norma or "nacional" in t_norma:
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

    # --- TENSION MT (kV) — excluir kVA para no confundir 75kVA con 75 kV ---
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kv(?!a)", t)
    if m:
        cfg["tension"] = m.group(1).replace(",", ".") + " kV"

    # --- CALIBRE CONDUCTOR ---
    # Formato N/0 (AWG 1/0, 2/0, 4/0) — la barra con cero no es relacion TC/TP
    mc_s0 = re.search(r"\b(\d+)/0\b", t)
    mc_awg = re.search(r"\bawg\s*(\d+(?:/0)?)\b", t)
    if mc_awg:
        cfg["calibre_conductor"] = "AWG " + mc_awg.group(1)
        entendido.append(f"Calibre AWG {mc_awg.group(1)}")
    elif mc_s0:
        cfg["calibre_conductor"] = mc_s0.group(1) + "/0"
        entendido.append(f"Calibre {mc_s0.group(1)}/0")

    # --- DPS / PARARRAYOS: cantidad (banco de N) ---
    # draw_unifilar_generico() YA dibuja pararrayos siempre que hay trafo o
    # es indirecta (RETIE), sin necesidad de pedirlo -- esto solo captura
    # CUANTOS, si el usuario lo menciona explicitamente. Si no lo menciona,
    # dps_cantidad no se fija y el default (1) aplica sin preguntar nada.
    m_dps = re.search(r"banco\s+de\s+(\d+)\s*(?:dps|pararrayos)|(\d+)\s*(?:dps|pararrayos)", t)
    if m_dps:
        n_dps = m_dps.group(1) or m_dps.group(2)
        cfg["dps_cantidad"] = int(n_dps)
        entendido.append(f"DPS: banco de {n_dps}")

    # --- TENDIDO DEL CONDUCTOR: aereo (default, no se anota) / subterraneo ---
    if re.search(r"\b(subterraneo|subterranea|enterrad[oa]|ductos?)\b", t):
        cfg["tendido"] = "subterraneo"
        entendido.append("Tendido: subterraneo")

    # --- NIVEL DE TENSION MT (ej. 13.2 kV) ---
    valor_mt = _extraer_vmt(t)
    if valor_mt:
        cfg["v_mt"] = f"{valor_mt} kV"
        entendido.append(f"Tension MT {valor_mt} kV")

    # --- IDENTIFICACION DEL CIRCUITO (ej. "circuito Magdalena", "cto: 5") ---
    m_cto = re.search(r"\b(?:circuito|cto)\s*:?\s*([A-Za-zÀ-ÿ0-9]+)\b", text, re.IGNORECASE)
    if m_cto:
        cfg["circuito"] = m_cto.group(1)
        entendido.append(f"Circuito: {m_cto.group(1)}")

    # --- INTERRUPTOR / PROTECCION (deteccion global) ---
    ma_int = re.search(
        r"(?:proteccion|interruptor|breaker|totalizador)\s*(?:de\s*)?(\d+)\s*a(?:mp|mps|mperios)?\b", t
    )
    if ma_int:
        cfg["interruptor"] = ma_int.group(1) + " A"
        entendido.append(f"Interruptor {ma_int.group(1)} A")

    # --- TRANSFORMADOR ---
    tiene_trafo = any(x in t for x in ["transformador", "trafo"])
    if tiene_trafo and any(x in t for x in ["kva", "compartido", "propio", "privado", "exclusivo", "unifilar", "totalizador"]):
        cfg["instalacion"] = "trafo"
        mk = re.search(r"(\d+(?:[.,]\d+)?)\s*kva", t)
        if mk:
            cfg["trafo_kva"] = mk.group(1).replace(",", ".")
        if not cfg.get("trafo_tipo"):              # sin fase propia del trafo: la del sistema que se dijo
            if "bifasic" in t:
                cfg["trafo_tipo"] = "bifasico"
            elif "monofasic" in t:
                cfg["trafo_tipo"] = "monofasico"
            elif "trifasic" in t:
                cfg["trafo_tipo"] = "trifasico"
        mcc = re.search(r"(\d+)\s*cortacircuit", t)
        if mcc: cfg["n_cc"] = int(mcc.group(1))
        mtc = re.search(r"(\d+)\s*tc", t)
        if mtc: cfg["n_tc"] = int(mtc.group(1))
        # interruptor dentro del bloque trafo si no fue detectado antes
        if not cfg.get("interruptor"):
            ma = re.search(r"(\d+)\s*a(?:mp|mps|mperios)?\b", t)
            if ma: cfg["interruptor"] = ma.group(1) + " A"
        # --- USO DEL TRAFO: exclusivo vs compartido ---
        # Un trafo COMPARTIDO alimenta un barraje BT del que se derivan varios
        # usuarios, cada uno con su propio medidor DIRECTO (no hay un solo
        # medidor semidirecta/indirecta para todos). Si el texto no especifico
        # un tipo de medida explicito, el punto de este usuario es DIRECTA.
        if "compartido" in t:
            cfg["trafo_uso"] = "compartido"
            if tipo_count == 0:
                cfg["tipo"] = "directa"
                entendido.append(
                    "Trafo compartido -> tipo forzado a DIRECTA "
                    "(cada usuario con medidor propio)"
                )
            m_us = re.search(r"(\d+)\s*(?:otros?\s*)?usuario", t)
            if m_us:
                cfg["trafo_n_usuarios"] = m_us.group(1)
                entendido.append(f"{m_us.group(1)} usuarios compartiendo el trafo")
            if any(x in t for x in ["gabinete", "cuarto de medidor", "cajilla compartida", "encerrado"]):
                cfg["trafo_gabinete"] = True
            elif any(x in t for x in ["red abierta", "a la intemperie", "poste", "aereo", "aérea"]):
                cfg["trafo_gabinete"] = False
        else:
            if any(x in t for x in ["exclusivo", "propio", "privado"]):
                cfg["trafo_uso"] = "exclusivo"
            # Trafo de uso propio/exclusivo: casi siempre se quiere ver la
            # cadena completa RED->TRAFO->MEDIDOR, por eso se fuerza unifilar.
            cfg["salida"] = "unifilar"

    # --- VARIOS TRANSFORMADORES, UBICACION DE LA MEDIDA, CELDA (campos de acta) ---
    faltante_acta = []
    _extraer_trafos(t, cfg, entendido, faltante_acta)
    _extraer_acta(t, text, cfg, entendido)
    _extraer_gabinete(t, text, cfg, entendido, tipo_count)

    # --- SECCIONADOR: posicion respecto al TRAFO (lo unico que dibuja el motor) ---
    # "antes"   = entre el punto de medida y el trafo (lado MT)
    # "despues" = aguas abajo del trafo (lado BT)
    # Sin esto, "seccionador despues" en texto libre se descartaba sin avisar.
    if re.search(r"\bseccionador", t) and not re.search(r"\bsin\s+seccionador", t):
        # Solo la clausula que sigue a la palabra (hasta coma/punto/";"), para
        # no contaminarse con otra frase tipo "proteccion despues del medidor".
        clausula = re.split(r"[,;]|\.(?:\s|$)", t[t.index("seccionador"):], maxsplit=1)[0]
        pos = None
        if re.search(r"antes\s+d(?:el|e\s+la)\s+(?:trafo|transformador)|lado\s+(?:de\s+)?(?:red|mt)\b|media\s+tension|\bmt\b", clausula):
            pos = "antes"
        elif re.search(r"despues\s+d(?:el|e\s+la)\s+(?:trafo|transformador)|lado\s+(?:de\s+)?(?:carga|bt)\b|baja\s+tension|\bbt\b", clausula):
            pos = "despues"
        elif re.search(r"despues\s+d(?:e\s+la|el|e)\s+(?:medida|medicion|medidor|punto\s+de\s+medida)", clausula):
            # En indirecta la medida esta en MT, AGUAS ARRIBA del trafo: un
            # seccionador "despues de la medida" queda fisicamente entre la
            # medida y el trafo -> "antes" del trafo. En semi/directa la
            # medida es en BT (aguas abajo del trafo) -> "despues".
            pos = "antes" if cfg["tipo"] == "indirecta" else "despues"
        elif re.search(r"antes\s+d(?:e\s+la|el|e)\s+(?:medida|medicion|medidor|punto\s+de\s+medida)", clausula):
            pos = "antes"   # lo mas cercano que dibuja el motor: lado red/MT
        if pos is None:
            pos = "antes"   # mencionado sin posicion: el caso tipico
            entendido.append("Seccionador: antes del trafo (lado MT) — posicion por defecto")
        else:
            entendido.append("Seccionador: " + ("antes del trafo (lado MT)" if pos == "antes"
                                                  else "despues del trafo (lado BT)"))
        cfg["seccionador"] = pos
        if re.search(r"\babierto\b", clausula):       # masculino: "red abierta" no cuenta
            cfg["seccionador_estado"] = "abierto"
            entendido.append("Seccionador ABIERTO")

    # --- ESTILO del unifilar (solo existe para indirecta): "detallado" / "con plano de simbologia"
    if cfg["tipo"] == "indirecta" and re.search(r"\bdetallad[oa]\b|plano\s+de\s+simbolog", t):
        cfg["estilo"] = "detallado"
        entendido.append("Estilo: detallado (con plano de simbologia)")

    # --- CONEXION (simetrica / asimetrica) — solo aplica a medida directa ---
    if re.search(r"asimetr", t):
        cfg["conexion"] = "asimetrica"
        entendido.append("Conexion: asimetrica")
    elif re.search(r"simetr", t):
        cfg["conexion"] = "simetrica"
        entendido.append("Conexion: simetrica")

    # --- VALIDAR FALTANTE ---
    faltante = []
    if cfg["tipo"] == "indirecta" and not cfg["rel_tc"]:
        faltante.append("relacion de TC (ej. 200/5)")
    if cfg["tipo"] == "indirecta" and not cfg["rel_tp"]:
        faltante.append("relacion de TP (ej. 13200/120)")
    # M4: semidirecta tambien necesita RTC para etiquetar correctamente el diagrama
    if cfg["tipo"] == "semidirecta" and not cfg["rel_tc"]:
        faltante.append("relacion de TC (ej. 200/5)")
    faltante += faltante_acta

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
