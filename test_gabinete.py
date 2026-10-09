#!/usr/bin/env python3
"""Plano de GABINETE COMPARTIDO (medida directa con otros usuarios) de punta a punta.

Caso real que lo motivo: el usuario describio por el dialogo IA "medida directa, MT 13,2 kV,
transformador interno en subestacion, gabinete interior compartido con 4 medidores mas,
totalizador posterior al medidor, 220 V" y el bot devolvio solo "barraje 220 V -> medidor -> carga";
luego escribio "no mostro el cuadro de lo compartido con 4 mas" y esa correccion cayo en la consulta
normativa (timeout de Gemini). Cubre:
  0. FIDELIDAD con el script de Claude Chat que el usuario pidio "tal cual": con los mismos datos el plano trae EXACTAMENTE
     los mismos textos (titulo, subtitulo, bajante, seccionador, trafo, barraje, otros usuarios, medidor, totalizador, notas);
  1. el dibujo (17 variantes) sin textos/cables/recuadros superpuestos (detector de test_frontera);
  2. el despacho a draw_unifilar_gabinete solo para directa + punto compartido;
  3. el parser (texto libre) y la red de seguridad _completar_con_parser;
  4. el dialogo IA con el SDK REAL (transporte simulado): JSON incompleto -> plano completo;
  5. correcciones despues de un diagrama (no van a la consulta normativa);
  6. coherencia y caption.
`GAB_OUT=<dir>` guarda los PNG de las 17 variantes."""
import sys, os, asyncio, json, logging, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
logging.disable(logging.CRITICAL)
import anthropic
try:
    import httpx2 as H
except ImportError:                      # anthropic 0.x
    import httpx as H
import bot, diagram_engine as de, test_frontera as tf
from parser import DEFAULT, parse_spec

MALOS = 0
def chk(cond, msg):
    global MALOS
    MALOS += not cond
    print("OK  " if cond else "MAL ", msg)

# ── 0) fidelidad con el script del ejemplo ───────────────────────────────────
# Textos que dibuja el script del usuario (DATOS por defecto: 13,2 kV, bajante monopolar, seccionador RA8, trafo sin kVA,
# 208-120 V, 5 medidores, medida 1, interior, totalizador despues del medidor, sin clase ni amperaje).
TEXTOS_EJEMPLO = [
    "DIAGRAMA UNIFILAR – MEDIDA DIRECTA INTERIOR EN GABINETE COMPARTIDO (5 MEDIDORES)",
    "Red MT 13,2 kV  |  Transformador interno  |  Barraje común con totalizador posterior al medidor",
    "RED DE DISTRIBUCIÓN MT\n13,2 kV – 3F", "Bajante en cable\nmonopolar (3 × 1/C)\n13,2 kV", "SUBESTACIÓN INTERIOR",
    "Seccionador MT\n(según norma RA8)\n13,2 kV – 3P",
    "Transformador trifásico\n___ kVA  (por definir)\n13,2 kV / 208-120 V\n(verificar tensión BT)",
    "SPT neutro BT y masas", "GABINETE DE MEDIDA – 5 MEDIDORES (INTERIOR)", "Acometida BT 3F + N + PE", "Barraje BT\n(3F + N)",
    "Medida\n2", "otro\nusuario", "Medida\n3", "otro\nusuario", "Medida\n4", "otro\nusuario", "Medida\n5", "otro\nusuario",
    "kWh\nkVArh", "Medidor trifásico\ndirecto (sin TC)\nclase ___", "Totalizador termomagnético 3P\n___ A  (por definir)",
    "CARGA DEL USUARIO", "Medida objeto del unifilar",
]
NOTAS_EJEMPLO = [
    "NOTAS:",
    "1. Valores marcados con ___ pendientes de confirmar en campo: kVA del transformador, clase del medidor, amperaje del totalizador 3P.",
    "2. Tensión BT asumida; verificar en placa del transformador.",
    "3. Totalizador termomagnético ubicado después del medidor, en el mismo ramal del barraje.",
    "4. Seccionador MT antes del transformador conforme a norma RA8 del operador de red.",
]

def textos_de(cfg):
    c, _ = bot._verificar_coherencia(dict(DEFAULT, **dict({"salida": "unifilar"}, **cfg)))
    fig = tf.capturar(c)
    t = [x.get_text() for x in fig.axes[0].texts]
    mal = tf.defectos(fig); plt.close(fig)
    return t, mal

def prueba_fidelidad():
    cfg = dict(sistema="tri4h", tipo="directa", norma="RA8", instalacion="trafo", trafo_uso="compartido", trafo_n_usuarios="4",
               trafo_gabinete=True, v_mt="13.2 kV", seccionador="antes", totalizador="despues", ubicacion_trafo="interior",
               bajante_mt="monopolar")
    t, mal = textos_de(cfg)
    chk(sorted(x for x in t if not x.startswith(("NOTAS", "1.", "2.", "3.", "4."))) == sorted(TEXTOS_EJEMPLO),
        "fidelidad: mismos datos que el script del ejemplo -> los MISMOS textos del plano")
    chk([x for x in t if x.startswith(("NOTAS", "1.", "2.", "3.", "4."))] == NOTAS_EJEMPLO, "fidelidad: las 4 notas son las del ejemplo")
    chk(not mal, f"fidelidad: ese plano no tiene superposiciones {mal[:3] if mal else ''}")
    # con la tension dada por el usuario ya no es "asumida": desaparecen el aviso y la nota 2 (es lo logico)
    t2, _m = textos_de(dict(cfg, tension_bt="220"))
    chk(any("220-127 V" in x for x in t2) and not any("verificar tensión BT" in x for x in t2)
        and not any(x.startswith("2. Tensión BT asumida") for x in t2), "fidelidad: con 220 V dado -> '220-127 V' y sin aviso de tension asumida")
    # tripolar y rotulos libres del bajante
    chk(de._bajante_lineas("tripolar") == ["Bajante en cable", "tripolar (1 × 3/C)"], "bajante: 'tripolar' -> (1 × 3/C)")
    chk(de._bajante_lineas("cable monopolar (3 × 1/C)") == ["Bajante en cable", "monopolar (3 × 1/C)"], "bajante: no repite 'cable'")
    chk(de._bajante_lineas("") == ["Bajante MT"] and de._bajante_lineas("aislado XLPE") == ["Bajante: aislado XLPE"],
        "bajante: sin dato no se inventa la formacion del cable")

def prueba_posicion():
    # ESTE medidor en la 3.a posicion de 5: las otras quedan numeradas 1, 2, 4 y 5 y el barraje las une
    cfg = dict(BASE, trafo_n_usuarios="4", posicion_medida="3")
    c, _ = bot._verificar_coherencia(dict(cfg))
    fig = tf.capturar(c); ax = fig.axes[0]
    textos = [t.get_text() for t in ax.texts]
    chk(sorted(x for x in textos if x.startswith("Medida\n")) == ["Medida\n1", "Medida\n2", "Medida\n4", "Medida\n5"],
        "posicion 3 de 5: los otros usuarios son 1, 2, 4 y 5")
    xm = next(t.get_position()[0] for t in ax.texts if t.get_text().startswith("kWh"))
    x2 = next(t.get_position()[0] for t in ax.texts if t.get_text() == "Medida\n2")
    x4 = next(t.get_position()[0] for t in ax.texts if t.get_text() == "Medida\n4")
    chk(x2 < xm < x4, "posicion 3 de 5: el medidor propio queda entre la 2 y la 4")
    mal = tf.defectos(fig); plt.close(fig)
    chk(not mal, f"posicion 3 de 5: sin superposiciones {mal[:3] if mal else ''}")
    for malo in ("9", "0", "x", ""):
        t, _m = textos_de(dict(cfg, posicion_medida=malo))
        chk(sorted(x for x in t if x.startswith("Medida\n")) == ["Medida\n2", "Medida\n3", "Medida\n4", "Medida\n5"],
            f"posicion invalida {malo!r}: se ignora y queda de primero")
    c, _ = parse_spec("directa trifasica RA8 gabinete compartido con 4 medidores mas, mi medida es la 3")[0:2]
    chk(c.get("posicion_medida") == "3" and c.get("trafo_n_usuarios") == "4", "parser: 'mi medida es la 3' -> posicion_medida=3")
    chk("posicion_medida" not in parse_spec("directa trifasica RA8 trafo exclusivo 150 kVA posicion 2")[0],
        "parser: sin punto compartido no inventa posicion")

# ── 0b) "compartido con 8" y tension MT en cualquier formato ─────────────────
def prueba_conteo_y_mt():
    base = "medida directa trifasica RA8 "
    casos = {"compartido con 8": "8", "trafo compartido con 8 usuarios": "8", "gabinete compartido con 8 mas": "8",
             "compartido con 8 medidores": "8", "compartido entre 9 usuarios": "8", "compartido con otros 8": "8",
             "compartido, 8 usuarios": "8", "gabinete compartido somos 9": "8", "gabinete de 5 medidores": "4",
             "gabinete con 12 medidores": "11", "5 medidores en total, compartido": "4", "compartido con 4 medidores mas": "4"}
    for frase, otros in casos.items():
        c = parse_spec(base + frase)[0]
        chk(c.get("trafo_n_usuarios") == otros and c.get("trafo_uso") == "compartido", f"conteo: '{frase}' -> {otros} otros")
    for frase in ("compartido con 4 hilos", "compartido con 100 A", "trafo exclusivo 150 kVA"):
        chk(not parse_spec(base + frase)[0].get("trafo_n_usuarios"), f"conteo: '{frase}' NO es una cantidad de usuarios")
    mt = {"MT 13.2 kV": "13.2 kV", "media tension 13.2kv": "13.2 kV", "en MT 13200 V": "13.2 kV", "MT 13.200 voltios": "13.2 kV",
          "media tension de 34,5 KV": "34.5 kV", "tension media 13,2": "13.2 kV", "MT 13200": "13.2 kV", "MT de 13.2": "13.2 kV",
          "alimentado en media tension (13.2 kV)": "13.2 kV", "red MT a 11.4 kV": "11.4 kV"}
    for frase, esperado in mt.items():
        c = parse_spec(base + "gabinete compartido con 4 mas, " + frase)[0]
        chk(c.get("v_mt") == esperado, f"tension MT: '{frase}' -> {esperado} (v_mt={c.get('v_mt')!r})")
    for frase in ("220 V", "tension 208/120 V", "75 kVA", "TP 13200/120"):
        chk(not parse_spec(base + "gabinete compartido con 4 mas, " + frase)[0].get("v_mt"), f"tension MT: '{frase}' NO es MT")
    c = parse_spec(base + "compartido con 8, media tension 13200 V, 220 V")[0]
    chk(c.get("instalacion") == "trafo" and c.get("tension_bt") == "220", "MT dada en punto compartido -> hay transformador; 220 V es la BT")
    for v, esperado in (("13.2 kV", 13.2), ("13200 V", 13.2), ("13.200 V", 13.2), ("13200", 13.2), ("13.2", 13.2), ("34.5kV", 34.5),
                        ("220 V", None), ("220", None), ("", None), (None, None)):
        chk(de._kv_de(v) == esperado, f"_kv_de({v!r}) = {esperado}")

def prueba_ocho_usuarios():
    # coherencia: MT dada + punto compartido -> red MT y trafo (antes se descartaba la MT)
    c, notas = bot._verificar_coherencia(dict(DEFAULT, tipo="directa", instalacion="barraje", trafo_uso="compartido",
                                              trafo_n_usuarios="8", trafo_gabinete=True, v_mt="13200 V"))
    chk(c["instalacion"] == "trafo" and c["v_mt"] == "13.2 kV" and any("media tensión (13,2 kV)" in n for n in notas),
        "coherencia: v_mt + punto compartido -> instalacion=trafo, v_mt normalizada y aviso")
    c, notas = bot._verificar_coherencia(dict(DEFAULT, tipo="semidirecta", rel_tc="200/5", instalacion="barraje", v_mt="13.2 kV"))
    chk("v_mt" not in c, "coherencia: semidirecta sin trafo sigue descartando v_mt (sin cambios)")
    # dibujo: se muestran TODOS los otros usuarios y la tension MT
    for otros, extra in ((8, {}), (11, {}), (8, dict(respaldo=True, posicion_medida="5"))):
        t, mal = textos_de(dict(BASE, trafo_n_usuarios=str(otros), **extra))
        pos = int(extra.get("posicion_medida", 1))
        esperados = sorted(f"Medida\n{i}" for i in range(1, otros + 2) if i != pos)
        chk(sorted(x for x in t if x.startswith("Medida\n")) == esperados and not any("por definir: se muestran" in x for x in t),
            f"{otros} otros usuarios{' (respaldo, pos 5)' if extra else ''}: se dibujan TODAS las posiciones")
        chk(any(x.startswith("RED DE DISTRIBUCIÓN MT") and "13,2 kV" in x for x in t) and any("13,2 kV / 220-127 V" in x for x in t),
            f"{otros} otros usuarios: el plano rotula la media tension 13,2 kV")
        chk(not mal, f"{otros} otros usuarios: sin superposiciones {mal[:3] if mal else ''}")
    t, mal = textos_de(dict(BASE, trafo_n_usuarios="20"))
    chk(sum(x.startswith("Medida\n") for x in t) == 11 and any(x.startswith("+9\nmedidores") for x in t) and not mal,
        f"20 otros usuarios: 11 posiciones + '+9 medidores más' sin superposiciones {mal[:3] if mal else ''}")
    chk(any("El gabinete tiene 21 medidores" in x for x in t), "20 otros usuarios: la nota explica el resumen")

# ── 1) dibujo ────────────────────────────────────────────────────────────────
BASE = dict(DEFAULT, salida="unifilar", sistema="tri4h", tipo="directa", norma="RA8", instalacion="trafo",
            trafo_uso="compartido", trafo_n_usuarios="4", trafo_gabinete=True, v_mt="13.2 kV", tension_bt="220",
            seccionador="antes", totalizador="despues")
VARIANTES = {
    "a_base": {},
    "b_tot_antes": dict(totalizador="antes", proteccion_antes="100 A"),
    "c_respaldo": dict(respaldo=True),
    "d_respaldo_tot_antes": dict(respaldo=True, totalizador="antes", proteccion_antes="100 A"),
    "e_mono": dict(sistema="mono", tension_bt="120"),
    "f_bif": dict(sistema="bifasico", tension_bt="240"),
    "g_tri3h": dict(sistema="tri3h"),
    "h_sin_usuarios": dict(trafo_n_usuarios=""),
    "i_12_usuarios": dict(trafo_n_usuarios="12"),
    "j_red_abierta": dict(trafo_gabinete=False),
    "k_sin_trafo": dict(instalacion="barraje"),
    "l_sin_nada": dict(seccionador="", totalizador="", tension_bt="", v_mt="", trafo_n_usuarios="1"),
    "m_todo": dict(trafo_kva="300", proteccion_despues="200 A", interruptor_polos="3", interruptor_tipo="caja moldeada",
                   clase_medidor="0,5S", bajante_mt="cable monopolar (3 × 1/C)", calibre_conductor="3×2/0 AWG",
                   circuito="Magdalena", proyecto="Edificio Aurora", dps_cantidad=3,
                   planta_respaldo={"existe": True, "kva": "150", "transferencia": "automatica"},
                   tendido="subterraneo", ubicacion_trafo="poste", seccionador="despues", trafo_n_usuarios="3"),
    "n_seccionador_abierto": dict(seccionador_estado="abierto"),
    "o_sin_seccionador": dict(seccionador=""),
    "p_1_usuario": dict(trafo_n_usuarios="1"),
    "q_sin_totalizador": dict(totalizador=""),
    "r_8_usuarios": dict(trafo_n_usuarios="8"),
    "s_12_usuarios_respaldo_pos4": dict(trafo_n_usuarios="12", respaldo=True, posicion_medida="4", totalizador="antes", proteccion_antes="100 A"),
    "t_20_usuarios": dict(trafo_n_usuarios="20"),
    "u_trafo_tri_medida_bif": dict(sistema="bifasico", trafo_tipo="trifasico", tension_bt="208/120", trafo_kva="150"),
    "v_trafo_tri_medida_mono_respaldo": dict(sistema="mono", trafo_tipo="trifasico", tension_bt="120", respaldo=True,
                                              totalizador="antes", proteccion_antes="40 A", posicion_medida="3"),
    "w_trafo_mono_medida_bif": dict(sistema="bifasico", trafo_tipo="monofasico", tension_bt="240"),
    "x_trafo_bif_medida_mono": dict(sistema="mono", trafo_tipo="bifasico", tension_bt="240"),
    "y_medida_mono_sin_fase_trafo": dict(sistema="mono", tension_bt="120"),
    "z_trafo_mono_medida_tri": dict(sistema="tri4h", trafo_tipo="monofasico"),
}

def prueba_dibujo():
    out = os.environ.get("GAB_OUT")
    if out: os.makedirs(out, exist_ok=True)
    for nombre, kw in VARIANTES.items():
        c, _ = bot._verificar_coherencia(dict(BASE, **kw))
        fig = tf.capturar(c); mal = tf.defectos(fig); plt.close(fig)
        chk(not mal, f"dibujo {nombre}: sin textos/cables/recuadros superpuestos {mal[:3] if mal else ''}")
        if out: de.draw_unifilar_generico(c, os.path.join(out, nombre + ".png"))

def prueba_despacho():
    llamadas = []
    orig = de.draw_unifilar_gabinete
    de.draw_unifilar_gabinete = lambda cfg, p: (llamadas.append(1), orig(cfg, p))[1]
    try:
        import tempfile
        def dibuja(cfg):
            llamadas.clear()
            f = tempfile.NamedTemporaryFile(suffix=".png", delete=False); f.close()
            de.draw_unifilar_generico(bot._verificar_coherencia(dict(DEFAULT, salida="unifilar", **cfg))[0], f.name)
            ok_ = os.path.getsize(f.name) > 3000; os.remove(f.name)
            return bool(llamadas) and ok_ if cfg.get("_esperado") else (not llamadas and ok_)
        chk(dibuja(dict(tipo="directa", sistema="tri4h", instalacion="trafo", trafo_uso="compartido",
                        trafo_n_usuarios="4", _esperado=True)), "despacho: directa + compartido -> plano de gabinete")
        chk(dibuja(dict(tipo="directa", sistema="tri4h", trafo_n_usuarios="3", _esperado=True)),
            "despacho: directa con otros usuarios (sin decir 'compartido') -> plano de gabinete")
        chk(dibuja(dict(tipo="directa", sistema="tri4h", instalacion="trafo", trafo_uso="exclusivo")),
            "despacho: directa exclusiva -> el plano de siempre")
        chk(dibuja(dict(tipo="semidirecta", sistema="tri4h", rel_tc="200/5", instalacion="trafo", trafo_uso="compartido")),
            "despacho: semidirecta compartida -> el plano de siempre")
        chk(dibuja(dict(tipo="indirecta", sistema="tri4h", rel_tc="50/5", rel_tp="13200/120", v_mt="13.2 kV")),
            "despacho: indirecta -> el plano de siempre")
    finally:
        de.draw_unifilar_gabinete = orig

# ── 2) parser y red de seguridad ─────────────────────────────────────────────
FRASE = ("medida directa trifasica 4 hilos RA8, MT 13.2 kV, transformador interno en subestacion, "
         "gabinete interior compartido con 4 medidores mas, seccionador MT segun RA8, "
         "totalizador posterior al medidor, tension 220V")

def prueba_parser():
    cfg, _e, _f = parse_spec(FRASE)
    chk(cfg["tipo"] == "directa" and cfg["sistema"] == "tri4h" and cfg["norma"] == "RA8", "parser: directa, 4 hilos, RA8")
    chk(cfg["instalacion"] == "trafo" and cfg["trafo_uso"] == "compartido" and cfg["trafo_n_usuarios"] == "4",
        "parser: trafo compartido con 4 usuarios mas")
    chk(cfg["trafo_gabinete"] is True and cfg.get("ubicacion_trafo") == "interior", "parser: gabinete interior, subestacion interior")
    chk(cfg.get("totalizador") == "despues" and cfg.get("tension_bt") == "220" and cfg.get("v_mt") == "13.2 kV",
        "parser: totalizador despues, 220 V, MT 13.2 kV")
    chk(cfg["seccionador"] == "antes", "parser: seccionador MT")
    chk(cfg["respaldo"] is False, "parser: 'totalizador'/'medidores' no activan el medidor de respaldo")
    for frase, otros in (("gabinete de 5 medidores en total", "4"), ("trafo compartido con 6 usuarios", "6"),
                         ("compartido con 4 mas", "4"), ("gabinete con 12 medidores", "11")):
        c, _e, _f = parse_spec("directa trifasica RA8 " + frase)
        chk(c.get("trafo_n_usuarios") == otros and c["respaldo"] is False, f"parser: '{frase}' -> {otros} otros, sin respaldo")
    c, _e, _f = parse_spec("directa trifasica RA8 medidor principal y de respaldo")
    chk(c["respaldo"] is True, "parser: 'principal y de respaldo' si activa el respaldo")

def prueba_completar():
    # JSON como el que dejo la IA en el caso real: lo basico, sin el punto compartido
    ia = {"sistema": "tri4h", "tipo": "directa", "salida": "unifilar", "norma": "RA8",
          "instalacion": "barraje", "tension_bt": "220", "respaldo": False}
    nuevo, tocados = bot._completar_con_parser(ia, [FRASE])
    chk(nuevo["instalacion"] == "trafo" and nuevo["trafo_uso"] == "compartido" and nuevo["trafo_n_usuarios"] == "4",
        f"completar: 'barraje' -> trafo compartido con 4 mas ({tocados})")
    chk(nuevo["trafo_gabinete"] is True and nuevo["totalizador"] == "despues" and nuevo["v_mt"] == "13.2 kV"
        and nuevo["seccionador"] == "antes" and nuevo["ubicacion_trafo"] == "interior",
        "completar: recupera gabinete, totalizador, MT, seccionador y ubicacion")
    chk(nuevo["tension_bt"] == "220" and ia["instalacion"] == "barraje", "completar: no muta la entrada ni pisa lo que la IA si puso")
    # lo que la IA puso explicitamente manda (relleno, no sobrescritura)
    nuevo, _t = bot._completar_con_parser(dict(ia, v_mt="34.5 kV", trafo_gabinete=False), [FRASE])
    chk(nuevo["v_mt"] == "34.5 kV" and nuevo["trafo_gabinete"] is False, "completar: el valor de la IA no se pisa")
    # sobrescribir (correcciones): el texto del usuario es la ultima palabra
    nuevo, _t = bot._completar_con_parser(dict(ia, trafo_n_usuarios="4", instalacion="trafo", trafo_uso="compartido"),
                                          ["compartido con 6 mas"], sobrescribir=True)
    chk(nuevo["trafo_n_usuarios"] == "6", "completar(sobrescribir): 'compartido con 6 mas' corrige 4 -> 6")
    # un texto que no habla de punto compartido no cambia nada
    ia2 = {"sistema": "tri4h", "tipo": "semidirecta", "norma": "CENS", "rel_tc": "200/5", "instalacion": "trafo",
           "trafo_uso": "exclusivo", "trafo_kva": "225"}
    nuevo, tocados = bot._completar_con_parser(ia2, ["semidirecta trifasica CENS 200/5 trafo propio 225 kVA"])
    chk(nuevo == ia2 and not tocados, f"completar: sin punto compartido el JSON queda igual ({tocados})")
    # entradas raras: nunca lanza
    for textos in ([], [""], ["   "], ["CENS RA8 directa"]):
        try:
            nuevo, _t = bot._completar_con_parser(dict(ia), textos); chk(nuevo == ia or True, f"completar: tolera {textos!r}")
        except Exception as e:
            chk(False, f"completar: lanzo {type(e).__name__} con {textos!r}")

# ── 1b) trafo trifasico + medida mono/bifasica (fases independientes) ───────────
def prueba_fases():
    # parser: la fase del trafo ya no es el sistema de la medida (antes: "Sistema ambiguo")
    casos = [
        ("medida directa bifasica, transformador trifasico de 150 kVA compartido con 4 mas, MT 13,2 kV", "bifasico", "trifasico"),
        ("transformador trifasico y medida monofasica, gabinete compartido con 3", "mono", "trifasico"),
        ("medida monofasica directa, trafo trifasico 75 kVA compartido", "mono", "trifasico"),
        ("trafo trifasico, medida bifasica 3 hilos, compartido con 5", "bifasico", "trifasico"),
        ("medida bifasica 3 hilos transformador monofasico compartido con 2", "bifasico", "monofasico"),
        ("transformador de 150 kVA trifasico compartido, medidor monofasico", "mono", "trifasico"),
        ("medida directa trifasica, transformador trifasico 225 kVA compartido con 4", "tri4h", "trifasico"),
        ("monofasica directa con trafo 25 kVA exclusivo", "mono", "monofasico"),
        ("transformador monofasico 25 kVA exclusivo, directa", "mono", "monofasico"),
        ("trifasica 3 hilos indirecta CENS 200/5 13200/120", "tri3h", None),
        ("bifasica 3 hilos directa", "bifasico", None),
    ]
    for frase, sis, tr in casos:
        try:
            c, _e, _f = parse_spec(frase)
            chk(c["sistema"] == sis and c.get("trafo_tipo") == tr, f"parser: {frase[:62]!r} -> medida {c['sistema']}, trafo {c.get('trafo_tipo')}")
        except ValueError as e:
            chk(False, f"parser: {frase[:62]!r} lanzo {e}")
    from parser import fases_dichas
    chk(fases_dichas("medida bifasica, transformador trifasico") == ("bifasico", "trifasico")
        and fases_dichas("trifasica 3 hilos") == ("tri3h", None) and fases_dichas("hola") == (None, None),
        "fases_dichas: (medida, trafo) tal como se dijeron")

    # dibujo: el trafo/barraje/acometida siguen al TRAFO; el ramal y el medidor, a la MEDIDA
    base = dict(BASE, tension_bt="208/120", trafo_kva="150")
    t, mal = textos_de(dict(base, sistema="bifasico", trafo_tipo="trifasico"))
    chk(not mal, f"trafo trifasico + medida bifasica: sin superposiciones {mal[:3] if mal else ''}")
    chk(any(x.startswith("Transformador trifásico") and "13,2 kV / 208-120 V" in x for x in t)
        and "Acometida BT 3F + N + PE" in t and "Barraje BT\n(3F + N)" in t
        and any(x.startswith("RED DE DISTRIBUCIÓN MT") and "13,2 kV – 3F" in x for x in t),
        "trafo trifasico + medida bifasica: trafo, acometida y barraje son trifasicos")
    chk("2F + N" in t and any(x.startswith("Medidor bifásico") for x in t)
        and any(x.startswith("Totalizador termomagnético 2P") for x in t) and not any(x == "kWh\nkVArh" for x in t),
        "trafo trifasico + medida bifasica: el ramal es 2F + N, medidor bifasico y totalizador 2P")
    chk(any("Medida bifásica 3 hilos" in x for x in t) and not any("Sistema bifásica" in x for x in t),
        "trafo trifasico + medida bifasica: el subtitulo dice 'Medida bifásica 3 hilos'")
    chk(any(x.startswith("4. Transformador trifásico y medida bifásica") and "3F + N" in x and "2F + N" in x for x in t),
        "trafo trifasico + medida bifasica: la nota explica la derivacion del barraje")
    t, mal = textos_de(dict(base, sistema="mono", trafo_tipo="trifasico"))
    chk("1F + N" in t and any(x.startswith("Medidor monofásico") for x in t) and "Barraje BT\n(3F + N)" in t
        and any(x.startswith("Totalizador termomagnético 1P") for x in t) and not mal,
        f"trafo trifasico + medida monofasica: ramal 1F + N, barraje 3F + N {mal[:3] if mal else ''}")
    # tension dada sola ("120") con trafo trifasico y medida mono -> es la fase-neutro del secundario trifasico
    t, _m = textos_de(dict(base, sistema="mono", trafo_tipo="trifasico", tension_bt="120"))
    chk(any("13,2 kV / 208-120 V" in x for x in t) and not any("120-69" in x for x in t), "trafo trifasico + medida mono con '120 V' -> 208-120 V")
    t, _m = textos_de(dict(base, sistema="mono", trafo_tipo="trifasico", tension_bt="220"))
    chk(any("13,2 kV / 220-127 V" in x for x in t), "trafo trifasico + medida mono con '220 V' -> 220-127 V")
    # trafo monofasico + medida bifasica (secundario de punto medio): barraje 2F + N
    t, mal = textos_de(dict(base, sistema="bifasico", trafo_tipo="monofasico", tension_bt="240"))
    chk(any(x.startswith("Transformador monofásico") for x in t) and "Barraje BT\n(2F + N)" in t and not mal,
        "trafo monofasico + medida bifasica: barraje 2F + N")
    # sin fase del trafo y medida mono: se dibuja segun la medida y se avisa (no se inventa trifasico)
    t, _m = textos_de(dict(base, sistema="mono"))
    chk("Barraje BT\n(1F + N)" in t and any(x.startswith("4. Fases del transformador sin indicar") for x in t),
        "medida mono sin fase de trafo: barraje segun la medida y nota 'fases del transformador sin indicar'")
    # medida y trafo de la misma fase: nada cambia (sin nota ni etiqueta extra)
    t, _m = textos_de(dict(base, sistema="tri4h", trafo_tipo="trifasico"))
    chk("2F + N" not in t and not any("Medida trifásica" in x or "sin indicar" in x for x in t),
        "medida y trafo trifasicos: sin etiquetas ni notas de fases distintas")
    # imposible: medida trifasica con trafo monofasico -> coherencia lo corrige (y avisa); el motor tambien
    c, notas = bot._verificar_coherencia(dict(BASE, sistema="tri4h", trafo_tipo="monofasico"))
    chk(c["trafo_tipo"] == "trifasico" and any("no puede alimentar una medida trifásica" in n for n in notas),
        "coherencia: medida trifasica + trafo monofasico -> trafo trifasico y aviso")
    c, notas = bot._verificar_coherencia(dict(BASE, sistema="bifasico", trafo_tipo="trifasico"))
    chk(c["trafo_tipo"] == "trifasico" and c["sistema"] == "bifasico" and not any("no puede alimentar" in n for n in notas),
        "coherencia: trafo trifasico + medida bifasica es valido (no se toca)")
    fig = tf.capturar(dict(BASE, sistema="tri4h", trafo_tipo="bifasico")); tx = [x.get_text() for x in fig.axes[0].texts]; plt.close(fig)
    chk(any("no alimenta una medida trifásica" in x for x in tx) and "Barraje BT\n(3F + N)" in tx,
        "motor: con datos imposibles (sin pasar por coherencia) dibuja trifasico y lo anota")
    # caption: se ve que trafo y medida son de distinta fase
    cap = bot._caption("Diagrama Unifilar", dict(BASE, sistema="bifasico", trafo_tipo="trifasico", trafo_kva="150"))
    chk("Bifásica" in cap and "Trafo: 150 kVA · trifásico" in cap, "caption: trafo trifásico con medida bifásica")
    cap = bot._caption("Diagrama Unifilar", dict(BASE, sistema="tri4h", trafo_tipo="trifasico", trafo_kva="150"))
    chk("Trafo: 150 kVA · compartido" in cap, "caption: misma fase -> sin repetir la fase del trafo")

    # red de seguridad del dialogo: la IA confunde las fases (todo trifasico) y el texto del usuario manda
    ia = {"sistema": "tri4h", "tipo": "directa", "salida": "unifilar", "norma": "RA8", "instalacion": "trafo",
          "trafo_uso": "compartido", "trafo_n_usuarios": "4", "trafo_gabinete": True, "v_mt": "13.2 kV"}
    frase = "medida directa bifasica RA8, transformador trifasico de 150 kVA, gabinete interior compartido con 4 mas, MT 13,2 kV"
    nuevo, tocados = bot._completar_con_parser(ia, [frase])
    chk(nuevo["sistema"] == "bifasico" and nuevo["trafo_tipo"] == "trifasico" and "trafo_tipo" in tocados,
        f"completar: 'trafo trifasico, medida bifasica' corrige lo que la IA confundio ({tocados})")
    nuevo, _t = bot._completar_con_parser(dict(ia, sistema="bifasico", trafo_tipo="trifasico"), [frase, "mejor el transformador es monofasico"])
    chk(nuevo["trafo_tipo"] == "monofasico" and nuevo["sistema"] == "bifasico", "completar: el ultimo mensaje que dice la fase del trafo gana")
    nuevo, tocados = bot._completar_con_parser(dict(ia), ["directa trifasica RA8, compartido con 4 mas"])
    chk(nuevo.get("sistema") == "tri4h" and "sistema" not in tocados, "completar: sin fase de trafo dicha no toca el sistema de la IA")
    # el prompt de la IA lo explica
    chk("INDEPENDIENTES" in bot.PROMPT_DIAGRAMA and "trafo_tipo" in bot.PROMPT_DIAGRAMA and "sistema de la MEDIDA" in bot.PROMPT_DIAGRAMA,
        "prompt: sistema (medida) y trafo_tipo son independientes")

async def prueba_fases_dialogo():
    llamadas = []
    orig = de.draw_unifilar_gabinete
    de.draw_unifilar_gabinete = lambda cfg, p: (llamadas.append(dict(cfg)), orig(cfg, p))[1]
    try:
        # la IA devuelve todo trifasico aunque el usuario dijo "medida bifasica, transformador trifasico"
        confuso = ('DIAGRAMA_LISTO\n```json\n{"sistema":"tri4h","tipo":"directa","salida":"unifilar","norma":"RA8",'
                   '"instalacion":"trafo","trafo_uso":"compartido","trafo_tipo":"trifasico","trafo_n_usuarios":"4",'
                   '"trafo_gabinete":true,"v_mt":"13.2 kV"}\n```')
        PETICIONES.clear(); bot._claude_client = cliente([ok(confuso)])
        u, c = Upd(), Ctx(modo_diagrama_ia=True)
        await bot._dialogo_diagrama(u, c, "medida directa bifasica RA8, transformador trifasico de 150 kVA, gabinete interior compartido con 4 mas, MT 13,2 kV")
        cfg = llamadas[0] if llamadas else {}
        chk(len(u.message.fotos) == 1 and cfg.get("sistema") == "bifasico" and cfg.get("trafo_tipo") == "trifasico",
            f"dialogo: medida bifasica + trafo trifasico llegan al motor ({cfg.get('sistema')}, {cfg.get('trafo_tipo')})")
        chk(u.message.fotos and "Bifásica" in u.message.fotos[0] and "trifásico" in u.message.fotos[0], "dialogo: el caption muestra las dos fases")
        # el parser tampoco lanza ya "Sistema ambiguo": se recupera ademas todo lo del gabinete aunque la IA lo deje vacio
        llamadas.clear()
        pobre = ('DIAGRAMA_LISTO\n```json\n{"sistema":"tri4h","tipo":"directa","salida":"unifilar","norma":"RA8",'
                 '"instalacion":"barraje","tension_bt":"208/120"}\n```')
        bot._claude_client = cliente([ok(pobre)])
        u, c = Upd(), Ctx(modo_diagrama_ia=True)
        await bot._dialogo_diagrama(u, c, "directa monofasica RA8, transformador trifasico 225 kVA, gabinete compartido con 6 mas, MT 13200 V")
        cfg = llamadas[0] if llamadas else {}
        chk(cfg.get("sistema") == "mono" and cfg.get("trafo_tipo") == "trifasico" and cfg.get("trafo_n_usuarios") == "6"
            and cfg.get("instalacion") == "trafo" and cfg.get("v_mt") == "13.2 kV" and cfg.get("trafo_kva") in ("225", None),
            f"dialogo: JSON pobre + 'trafo trifasico, medida monofasica' -> se recupera todo ({cfg.get('sistema')}, {cfg.get('trafo_tipo')}, {cfg.get('trafo_n_usuarios')})")
    finally:
        de.draw_unifilar_gabinete = orig

# ── 3) coherencia y caption ──────────────────────────────────────────────────
def prueba_coherencia():
    c, notas = bot._verificar_coherencia(dict(DEFAULT, tipo="directa", sistema="tri4h", trafo_n_usuarios="3"))
    chk(c["trafo_uso"] == "compartido", "coherencia: con otros usuarios el punto es compartido")
    chk(c["trafo_gabinete"] is False and any("RED ABIERTA" in n for n in notas), "coherencia: gabinete sin decir -> red abierta, avisado")
    c, notas = bot._verificar_coherencia(dict(DEFAULT, tipo="directa", instalacion="trafo", trafo_uso="compartido", trafo_gabinete=True))
    chk(any("cuántos otros usuarios" in n for n in notas), "coherencia: sin numero de usuarios -> avisa que dibujo 2 de ejemplo")
    chk(sum("RED ABIERTA" in n for n in notas) == 0, "coherencia: gabinete dicho -> sin aviso de red abierta")
    c, notas = bot._verificar_coherencia(dict(DEFAULT, tipo="directa", instalacion="trafo", trafo_uso="compartido",
                                              trafo_gabinete=None, trafo_n_usuarios="2"))
    chk(sum("RED ABIERTA" in n for n in notas) == 1, "coherencia: el aviso de red abierta sale una sola vez")
    cap = bot._caption("Diagrama Unifilar", dict(BASE))
    chk("Punto compartido: 5 medidores (4 más) · gabinete cerrado" in cap and "Totalizador después del medidor" in cap
        and "13.2 kV" in cap, "caption: resume el punto compartido")
    cap = bot._caption("Diagrama Unifilar", dict(BASE, trafo_kva=""))
    chk("kVA  " not in cap and "Trafo:  " not in cap, "caption: sin kVA no deja huecos")

# ── 4) dialogo IA con el SDK real ────────────────────────────────────────────
PETICIONES = []
def cliente(respuestas):
    it = iter(respuestas)
    def handler(request):
        PETICIONES.append(json.loads(request.content))
        return H.Response(200, json=next(it))
    return anthropic.AsyncAnthropic(api_key="sk-test", max_retries=0,
                                    http_client=H.AsyncClient(transport=H.MockTransport(handler)))
def ok(texto):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": bot.CLAUDE_MODEL_DIALOGO,
            "content": [{"type": "text", "text": texto}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}
class Msg:
    def __init__(self): self.textos, self.fotos = [], []
    async def reply_text(self, t, **k): self.textos.append(t)
    async def reply_photo(self, photo=None, caption=None, **k): self.fotos.append(caption)
    async def reply_chat_action(self, *a, **k): pass
class Upd:
    def __init__(self): self.message = Msg(); self.effective_message = self.message; self.effective_user = None
class Ctx:
    def __init__(self, **ud): self.user_data = dict(ud)

# lo que dejo la IA en el caso real: el plano basico, sin el punto compartido
JSON_BASICO = ('DIAGRAMA_LISTO\n```json\n{"sistema":"tri4h","tipo":"directa","salida":"unifilar","norma":"RA8",'
               '"instalacion":"barraje","tension_bt":"220","respaldo":false}\n```')

async def prueba_dialogo():
    llamadas = []
    orig = de.draw_unifilar_gabinete
    de.draw_unifilar_gabinete = lambda cfg, p: (llamadas.append(dict(cfg)), orig(cfg, p))[1]
    try:
        # a) la IA devuelve el JSON basico: el plano sale COMPLETO por la red de seguridad
        PETICIONES.clear(); bot._claude_client = cliente([ok(JSON_BASICO)])
        u, c = Upd(), Ctx(modo_diagrama_ia=True)
        await bot._dialogo_diagrama(u, c, FRASE)
        chk(len(u.message.fotos) == 1 and llamadas, "dialogo: el diagrama se genera con el plano de gabinete compartido")
        cfg = llamadas[0] if llamadas else {}
        chk(cfg.get("trafo_n_usuarios") == "4" and cfg.get("trafo_gabinete") is True and cfg.get("v_mt") == "13.2 kV"
            and cfg.get("instalacion") == "trafo" and cfg.get("totalizador") == "despues",
            "dialogo: llegan al motor los 4 otros usuarios, gabinete, MT 13.2 kV, trafo y totalizador")
        chk(u.message.fotos and "5 medidores (4 más)" in u.message.fotos[0], "dialogo: el caption dice '5 medidores (4 más)'")
        chk(c.user_data.get("modo_diagrama_ia") is False and c.user_data.get("ultimo_cfg", {}).get("trafo_uso") == "compartido"
            and c.user_data.get("ultimo_ts"), "dialogo: termina el modo IA y guarda ultimo_cfg/ultimo_ts")
        p = PETICIONES[0]
        txt_sis = json.dumps(p["system"], ensure_ascii=False)
        chk("GABINETE / PUNTO COMPARTIDO" in txt_sis and "NO PREGUNTES kVA" in txt_sis and "CORRECCION DE UN DIAGRAMA" in txt_sis,
            "dialogo: el prompt lleva las reglas del gabinete compartido y de correccion")
        chk(p["messages"][0]["content"].count("gabinete interior compartido") == 1, "dialogo: el mensaje del usuario viaja a la IA")

        # a2) la IA pregunta "¿cuantos usuarios comparten?", el usuario responde "8" y el JSON sale SIN la cantidad
        llamadas.clear(); PETICIONES.clear()
        sin_n = ('DIAGRAMA_LISTO\n```json\n{"sistema":"tri4h","tipo":"directa","salida":"unifilar","norma":"RA8",'
                 '"instalacion":"trafo","trafo_uso":"compartido","trafo_gabinete":true,"v_mt":"13200 V","tension_bt":"220"}\n```')
        bot._claude_client = cliente([ok("¿Cuántos otros usuarios comparten el punto?"), ok(sin_n)])
        u, c = Upd(), Ctx(modo_diagrama_ia=True)
        await bot._dialogo_diagrama(u, c, "directa trifasica RA8 gabinete compartido, MT 13200 V, 220 V")
        await bot._dialogo_diagrama(u, c, "8")
        cfg = llamadas[0] if llamadas else {}
        chk(len(u.message.fotos) == 1 and cfg.get("trafo_n_usuarios") == "8" and cfg.get("v_mt") == "13.2 kV",
            f"dialogo: la respuesta '8' a la pregunta de la IA llega como 8 otros usuarios y MT 13,2 kV ({cfg.get('trafo_n_usuarios')!r}, {cfg.get('v_mt')!r})")
        chk(u.message.fotos and "9 medidores (8 más)" in u.message.fotos[0] and "13.2 kV" in u.message.fotos[0],
            "dialogo: el caption dice 9 medidores (8 más) y 13.2 kV")
        ra = bot._otros_desde_respuesta([{"role": "model", "text": "¿Cuántos usuarios comparten?"}, {"role": "user", "text": "en total 9"}])
        chk(ra == 8, "respuesta 'en total 9' -> 8 otros")
        chk(bot._otros_desde_respuesta([{"role": "model", "text": "¿Qué amperaje tiene el totalizador?"}, {"role": "user", "text": "100"}]) is None,
            "un numero que responde a OTRA pregunta no se toma como cantidad de usuarios")

        # b) JSON incompleto + usuario SIN punto compartido: nada se inventa
        llamadas.clear(); PETICIONES.clear()
        bot._claude_client = cliente([ok(JSON_BASICO)])
        u, c = Upd(), Ctx(modo_diagrama_ia=True)
        await bot._dialogo_diagrama(u, c, "directa trifasica 4 hilos RA8 unifilar barraje 220 V")
        chk(len(u.message.fotos) == 1 and not llamadas, "dialogo: sin punto compartido el plano es el de siempre")
    finally:
        de.draw_unifilar_gabinete = orig

# ── 5) correcciones despues de un diagrama ───────────────────────────────────
def ctx_con_diagrama(hace=5, **extra):
    cfg = dict(DEFAULT, sistema="tri4h", tipo="directa", norma="RA8", salida="unifilar", instalacion="barraje", tension_bt="220")
    return Ctx(ultimo_cfg=dict(cfg, **extra), ultimo_ts=time.time() - hace)

def prueba_deteccion():
    bot._claude_client = object()                         # solo importa que exista
    c = ctx_con_diagrama()
    for t in ("NO MOSTRO EL CUADRO DE LO COMPARTIDO CON 4 MAS", "no mostró el gabinete compartido",
              "le falta el totalizador", "agrégale el seccionador de media tensión", "cámbialo a 208 V",
              "el diagrama está mal, falta el transformador", "quita el seccionador", "no se ve el medidor de respaldo",
              "puedes agregar el totalizador al diagrama?"):
        chk(bot._es_correccion_diagrama(c, t), f"correccion: '{t}' -> ajusta el ultimo diagrama")
    for t in ("¿Cuál es la distancia de seguridad en un tablero BT según el RETIE?",
              "que dice la CREG 038 sobre el seccionador?", "cuanto cuesta un medidor?", "hola",
              "falta mucho para el cierre del plazo de la resolucion CREG",
              "directa trifasica 4 hilos RA8 gabinete compartido con 4 medidores mas totalizador posterior al medidor "
              + "x" * 400):
        chk(not bot._es_correccion_diagrama(c, t), f"correccion: '{t[:60]}' -> NO es una correccion")
    chk(not bot._es_correccion_diagrama(ctx_con_diagrama(hace=bot.CORRECCION_VENTANA_S + 60), "no mostro el cuadro compartido"),
        "correccion: pasada la ventana de tiempo ya no aplica")
    chk(not bot._es_correccion_diagrama(Ctx(), "no mostro el cuadro compartido"), "correccion: sin diagrama previo no aplica")
    bot._claude_client = None
    chk(not bot._es_correccion_diagrama(c, "no mostro el cuadro compartido"), "correccion: sin cliente de IA no aplica")

async def prueba_correccion():
    llamadas = []
    orig = de.draw_unifilar_gabinete
    de.draw_unifilar_gabinete = lambda cfg, p: (llamadas.append(dict(cfg)), orig(cfg, p))[1]
    retie = []
    async def falso_retie(update, ctx, texto): retie.append(texto)
    orig_retie = bot._consulta_retie
    bot._consulta_retie = falso_retie
    try:
        # el caso real: "NO MOSTRO EL CUADRO DE LO COMPARTIDO CON 4 MAS" despues del diagrama basico
        PETICIONES.clear()
        json_ok = ('DIAGRAMA_LISTO\n```json\n{"sistema":"tri4h","tipo":"directa","salida":"unifilar","norma":"RA8",'
                   '"instalacion":"trafo","trafo_uso":"compartido","trafo_n_usuarios":"4","trafo_gabinete":true,'
                   '"tension_bt":"220","v_mt":"13.2 kV"}\n```')
        bot._claude_client = cliente([ok(json_ok)])
        u, c = Upd(), ctx_con_diagrama()
        await bot._procesar_texto(u, c, "NO MOSTRO EL CUADRO DE LO COMPARTIDO CON 4 MAS")
        chk(not retie, "correccion: NO va a la consulta normativa")
        chk(len(PETICIONES) == 1 and "DIAGRAMA ANTERIOR (JSON)" in PETICIONES[0]["messages"][0]["content"]
            and '"tension_bt": "220"' in PETICIONES[0]["messages"][0]["content"], "correccion: la IA recibe el JSON del diagrama anterior")
        chk(len(u.message.fotos) == 1 and llamadas and llamadas[0].get("trafo_n_usuarios") == "4",
            "correccion: se redibuja con el plano de gabinete y los 4 usuarios")
        chk(c.user_data.get("modo_diagrama_ia") is False and not c.user_data.get("historial_diagrama"),
            "correccion: cierra el modo IA y limpia el historial")

        # la IA hace UNA pregunta: la respuesta del usuario sigue por el mismo dialogo (no por la consulta normativa)
        PETICIONES.clear(); llamadas.clear()
        bot._claude_client = cliente([ok("¿Cuántos medidores hay en total?"), ok(json_ok)])
        u, c = Upd(), ctx_con_diagrama()
        await bot._procesar_texto(u, c, "agrega el cuadro de lo compartido")
        chk(u.message.textos and "total" in u.message.textos[-1] and c.user_data.get("modo_diagrama_ia") is True,
            "correccion: si falta algo, pregunta y deja el modo IA activo")
        await bot._dialogo_diagrama(u, c, "5 en total")      # lo que haria on_text con modo_diagrama_ia activo
        chk(len(u.message.fotos) == 1 and llamadas, "correccion: tras la respuesta se redibuja")
        chk(len(PETICIONES) == 2 and "DIAGRAMA ANTERIOR (JSON)" in PETICIONES[1]["messages"][0]["content"]
            and "5 en total" in PETICIONES[1]["messages"][0]["content"], "correccion: el 2.o turno conserva el JSON sembrado y la respuesta")

        # el parser corrige lo que la IA no cambio (el usuario es la ultima palabra)
        llamadas.clear()
        bot._claude_client = cliente([ok(json_ok)])              # la IA 'olvido' cambiar el 4
        u, c = Upd(), ctx_con_diagrama(instalacion="trafo", trafo_uso="compartido", trafo_n_usuarios="4", trafo_gabinete=True)
        await bot._procesar_texto(u, c, "no mostro el gabinete compartido con 6 mas")
        chk(llamadas and llamadas[0].get("trafo_n_usuarios") == "6", "correccion: 'compartido con 6 mas' gana sobre un JSON que dejo 4")

        # una consulta normativa sigue yendo a la consulta normativa
        retie.clear()
        u, c = Upd(), ctx_con_diagrama()
        await bot._procesar_texto(u, c, "¿Qué dice el RETIE sobre el seccionador en una subestación?")
        chk(retie, "correccion: una pregunta normativa NO se desvia")
    finally:
        de.draw_unifilar_gabinete = orig
        bot._consulta_retie = orig_retie

def main():
    prueba_fidelidad()
    prueba_posicion()
    prueba_conteo_y_mt()
    prueba_ocho_usuarios()
    prueba_dibujo()
    prueba_despacho()
    prueba_parser()
    prueba_completar()
    prueba_coherencia()
    prueba_fases()
    asyncio.run(prueba_dialogo())
    asyncio.run(prueba_fases_dialogo())
    prueba_deteccion()
    asyncio.run(prueba_correccion())
    print("\nFALLOS:", MALOS)
    sys.exit(1 if MALOS else 0)

if __name__ == "__main__":
    main()
