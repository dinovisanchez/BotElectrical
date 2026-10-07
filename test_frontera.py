#!/usr/bin/env python3
"""Unifilar con campos de ACTA: varios transformadores (paralelo / independientes), planta de
respaldo, celda de medida y punto de medicion (CLAUDE.md "Unifilar de frontera").

Ademas de comprobar que dibuja, cada escenario pasa por un DETECTOR de textos superpuestos
(texto contra texto, y texto contra cables): "no haya textos superpuestos" era un requisito
explicito de aceptacion, y que matplotlib no truene no lo garantiza."""
import sys, os, logging, itertools, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
logging.disable(logging.CRITICAL)
from parser import DEFAULT
import diagram_engine as de

QUIET = os.environ.get("QUIET")
SALIDA = os.environ.get("FRONTERA_OUT")          # carpeta donde dejar los PNG para revisarlos a ojo
TMP = os.path.join(tempfile.gettempdir(), "_frontera_test.png")

BASE = dict(DEFAULT, salida="unifilar", sistema="tri4h", norma="CENS", v_mt="11.4 kV", instalacion="trafo")
PL = {"existe": True, "kva": 150, "transferencia": "automatica"}
T2 = [{"kva": 300, "tipo": "trifasico", "uso": "exclusivo"}, {"kva": 300, "tipo": "trifasico", "uso": "compartido"}]

# (e)-(j) = escenarios de aceptacion del pedido; el resto, variantes que rompen primero
ESCENARIOS = {
    "e_2_paralelo_uno_compartido": dict(BASE, tipo="semidirecta", rel_tc="200/5", transformadores=T2,
                                        configuracion_transformadores="paralelo", proteccion_despues="400 A"),
    "f_2_independientes": dict(BASE, tipo="semidirecta", rel_tc="200/5", transformadores=T2[:1] + [{"kva": 150, "tipo": "trifasico", "uso": "exclusivo"}],
                               configuracion_transformadores="independientes", proteccion_despues="400 A"),
    "g_semidirecta_planta_automatica": dict(BASE, tipo="semidirecta", rel_tc="200/5", trafo_kva="300", trafo_uso="exclusivo",
                                            ubicacion_medida="BT", planta_respaldo=PL, proteccion_despues="400 A"),
    "h_indirecta_MT_con_celda": dict(BASE, tipo="indirecta", rel_tc="50/5", rel_tp="11400/120", trafo_kva="300", trafo_uso="exclusivo",
                                     ubicacion_medida="MT", celda_medida={"existe": True, "tipo": "AE319", "estado": "Bueno"}, seccionador="antes"),
    "i_indirecta_MT_sin_celda": dict(BASE, tipo="indirecta", rel_tc="50/5", rel_tp="11400/120", trafo_kva="300", trafo_uso="exclusivo",
                                     ubicacion_medida="MT", celda_medida={"existe": False}, seccionador="antes"),
    "j_e_mas_g": dict(BASE, tipo="semidirecta", rel_tc="200/5", transformadores=T2, configuracion_transformadores="paralelo",
                      planta_respaldo=PL, proteccion_despues="400 A"),
    # variantes
    "k_3_paralelo_manual": dict(BASE, tipo="semidirecta", rel_tc="300/5", configuracion_transformadores="paralelo", proteccion_despues="600 A",
                                transformadores=[{"kva": 225, "tipo": "trifasico", "uso": "exclusivo"}, {"kva": 150, "tipo": "trifasico", "uso": "compartido"},
                                                 {"kva": 112.5, "tipo": "trifasico", "uso": ""}],
                                planta_respaldo={"existe": True, "kva": None, "transferencia": "manual"}),
    "l_5_trafos_mostrar_4": dict(BASE, tipo="semidirecta", rel_tc="400/5",
                                 transformadores=[{"kva": 150, "tipo": "trifasico", "uso": "exclusivo"}] * 5),
    "m_2_indep_planta_compartido_primero": dict(BASE, tipo="semidirecta", rel_tc="200/5", configuracion_transformadores="independientes",
                                                transformadores=T2[::-1], planta_respaldo=PL, proteccion_despues="400 A"),
    "n_2_MT_indirecta_celda": dict(BASE, tipo="indirecta", rel_tc="100/5", rel_tp="11400/120", configuracion_transformadores="paralelo",
                                   transformadores=T2, celda_medida={"existe": True, "tipo": "AE319", "estado": "Regular"}, seccionador="antes",
                                   planta_respaldo=PL),
    "o_2_directa_mono": dict(BASE, tipo="directa", sistema="mono", transformadores=T2[:1] + [{"kva": 50, "tipo": "monofasico", "uso": "compartido"}],
                             proteccion_despues="100 A", respaldo=True),
    "p_semidirecta_BT_sin_planta": dict(BASE, tipo="semidirecta", rel_tc="200/5", trafo_kva="300", trafo_uso="exclusivo", ubicacion_medida="BT"),
}


def capturar(cfg):
    """Dibuja y devuelve la figura (el motor la cierra al terminar: se intercepta plt.close)."""
    capt = []; cierre = plt.close
    plt.close = lambda fig=None: capt.append(fig)
    try:
        de.draw_unifilar_generico(cfg, TMP)
    finally:
        plt.close = cierre
    return capt[-1]


def _seg_cruza_caja(p, q, caja):
    """Segmento p-q (pixeles) contra una caja (x0,y0,x1,y1): Liang-Barsky."""
    x0, y0, x1, y1 = caja
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if pp == 0:
            if qq < 0: return False
        else:
            t = qq / pp
            if pp < 0:
                if t > t1: return False
                t0 = max(t0, t)
            else:
                if t < t0: return False
                t1 = min(t1, t)
    return True


from matplotlib.text import Text

def defectos(fig):
    """[(texto, otro)] con cajas de texto que se pisan entre si o que cruza un cable."""
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    ax = fig.axes[0]
    cajas = []
    for t in ax.texts:
        if not t.get_visible() or not t.get_text().strip(): continue
        b = Text.get_window_extent(t, rend)       # solo el texto (en un Annotation, .get_window_extent suma la flecha)
        cajas.append((t.get_text().replace("\n", " / ")[:34], (b.x0 + 1, b.y0 + 1, b.x1 - 1, b.y1 - 1)))
    malos = []
    for (ta, ba), (tb, bb) in itertools.combinations(cajas, 2):
        if ba[0] < bb[2] and bb[0] < ba[2] and ba[1] < bb[3] and bb[1] < ba[3]:
            malos.append((ta, "TEXTO: " + tb))
    segs = []
    for l in ax.lines:
        if l.get_linewidth() < 1.0: continue
        xy = ax.transData.transform(list(zip(l.get_xdata(), l.get_ydata())))
        segs += [(tuple(a), tuple(b)) for a, b in zip(xy, xy[1:])]
    # texto que cruza el BORDE de una caja: solapa con ella pero no cabe entero dentro (el que esta
    # dentro, como el rotulo del bloque de pruebas, es correcto; el que esta fuera ni la toca)
    from matplotlib.patches import Rectangle, FancyBboxPatch
    for pt in ax.patches:
        if not isinstance(pt, (Rectangle, FancyBboxPatch)): continue
        eb = pt.get_window_extent(rend)
        for t, c in cajas:
            toca = c[0] < eb.x1 and eb.x0 < c[2] and c[1] < eb.y1 and eb.y0 < c[3]
            dentro = c[0] >= eb.x0 and c[2] <= eb.x1 and c[1] >= eb.y0 and c[3] <= eb.y1
            if toca and not dentro and (eb.width < 0.9 * fig.bbox.width):       # (no la ficha, que ocupa casi todo)
                malos.append((t, "BORDE DE CAJA"))
    for t, caja in cajas:
        for a, b in segs:
            if _seg_cruza_caja(a, b, caja):
                malos.append((t, "CABLE"))
                break
    return malos


def main():
    malos_tot = 0
    def chk(cond, msg):
        nonlocal malos_tot; malos_tot += not cond
        if not QUIET: print("OK  " if cond else "MAL ", msg)

    # ---- helpers de normalizacion ----
    chk(de._planta_de({"planta_respaldo": {"existe": "Sí", "kva": "150", "transferencia": "Automática"}})
        == {"existe": True, "kva": 150.0, "transf": "automatica", "transf_txt": "automática"}, "planta: 'Sí'/'Automática' -> normalizado")
    chk(de._planta_de({"planta_respaldo": {"existe": False}}) is None and de._planta_de({}) is None, "planta: sin planta -> None")
    chk(de._celda_de({"celda_medida": {"existe": "no", "tipo": "n.i"}}) == {"existe": False, "tipo": "", "estado": ""}, "celda: 'n.i' -> no informado")
    chk(de._ubic_medida({"tipo": "indirecta"}) == "MT" and de._ubic_medida({"tipo": "semidirecta"}) == "BT"
        and de._ubic_medida({"tipo": "semidirecta", "ubicacion_medida": "mt"}) == "MT", "ubicacion: por defecto MT en indirecta, BT en las demas")
    chk(len(de._trafos_de({"transformador": {"kva": 300}})) == 1 and len(de._trafos_de({"transformadores": [{"kva": 1}, {"kva": 2}]})) == 2,
        "transformador suelto = lista de uno")
    chk([t["kva"] for t in de._trafos_de({"transformadores": [{"kva": "300 kVA"}, {"kva": "-"}]})] == [300.0, None], "kVA '-' = no informado")
    chk(de._clasif_creg(600)[0] == 3 and de._clasif_creg(1500)[0] == 2 and de._clasif_creg(50)[0] == 4, "clasificacion CREG 038 por kVA total")
    chk(de._resumen_trafos(de._trafos_de({"transformadores": [{"kva": 300}, {"kva": 300}]})) == "2 × 300 kVA", "ficha: '2 × 300 kVA' si son iguales")

    # ---- parser de texto libre: el usuario escribe el pedido y el dibujo debe parecerse ----
    # (antes el parser ignoraba estos campos sin avisar y leia "planta de respaldo" como medidor de respaldo)
    from parser import parse_spec
    def pt(texto):
        cfg, ent, fal = parse_spec(texto)
        return cfg, ent, fal
    c, e, f = pt("2 transformadores de 300 kVA en paralelo, uno de ellos compartido, planta de respaldo de 150 kVA, "
                 "transferencia automatica, medida semidirecta CENS TC 600/5")
    chk([t["kva"] for t in c["transformadores"]] == ["300", "300"] and [t["uso"] for t in c["transformadores"]] == ["exclusivo", "compartido"]
        and c["configuracion_transformadores"] == "paralelo" and c["n_trafos"] == 2 and "trafo_kva" not in c,
        "parser: '2 transformadores de 300 kVA en paralelo, uno compartido' -> lista de 2, TRF2 compartido, paralelo")
    chk(c["planta_respaldo"] == {"existe": True, "kva": "150", "transferencia": "automatica"} and not c["respaldo"],
        "parser: 'planta de respaldo 150 kVA, transferencia automatica' -> planta (y NO medidor de respaldo)")
    c, e, f = pt("medida directa trifasica CENS 2 transformadores independientes de 300 y 150 kVA, trafo 1 compartido")
    chk([t["kva"] for t in c["transformadores"]] == ["300", "150"] and c["configuracion_transformadores"] == "independientes"
        and [t["uso"] for t in c["transformadores"]] == ["compartido", "exclusivo"], "parser: lista '300 y 150 kVA', independientes, 'trafo 1 compartido'")
    c, e, f = pt("indirecta CENS 50/5 11400/120 celda de medida AE319 estado bueno medida en MT trafo 300 kVA")
    chk(c["celda_medida"] == {"existe": True, "tipo": "AE319", "estado": "Bueno"} and c["ubicacion_medida"] == "MT" and "transformadores" not in c
        and c["trafo_kva"] == "300", "parser: celda AE319 bueno + medida en MT; un solo trafo sigue por trafo_kva")
    c, e, f = pt("indirecta CENS 50/5 11400/120 sin celda medida en MT trafo 300 kVA")
    chk(c["celda_medida"]["existe"] is False, "parser: 'sin celda' -> existe=false")
    c, e, f = pt("semidirecta CENS 200/5 trafo 300 kVA sin planta de respaldo")
    chk(c["planta_respaldo"]["existe"] is False and not c["respaldo"] and c["trafo_kva"] == "300", "parser: 'sin planta de respaldo' -> existe=false")
    c, e, f = pt("semidirecta tri4h CENS 200/5 trafos 300 kVA y 150 kVA")
    chk(len(c["transformadores"]) == 2 and c["transformadores"][1]["kva"] == "150", "parser: unidad repetida '300 kVA y 150 kVA'")
    c, e, f = pt("semidirecta CENS 200/5 dos transformadores en paralelo")
    chk(len(c["transformadores"]) == 2 and any("kVA" in x for x in f), "parser: 2 trafos sin kVA -> se pide el dato en 'faltante'")
    c, e, f = pt("monofasica directa respaldo")
    chk(c["respaldo"] is True and "planta_respaldo" not in c and "transformadores" not in c, "parser: 'respaldo' solo sigue siendo medidor de respaldo")
    c, e, f = pt("directa trifasica 4 hilos RA8 trafo compartido gabinete 13.2 kV proteccion 100 A")
    chk("transformadores" not in c and c["trafo_uso"] == "compartido" and c["trafo_gabinete"] is True, "parser: el caso de un trafo compartido no cambia")
    # de punta a punta: texto -> coherencia -> motor, sin superposiciones
    import bot
    for texto in ("2 transformadores de 300 kVA en paralelo, uno de ellos compartido, planta de respaldo 150 kVA, "
                  "transferencia automatica, medida semidirecta CENS TC 600/5 13.2 kV proteccion 400 A",
                  "indirecta CENS 50/5 11400/120 2 transformadores independientes de 300 y 150 kVA celda de medida AE319 "
                  "estado bueno medida en MT"):
        c, e, f = pt(texto); c["salida"] = "unifilar"
        c, _n = bot._verificar_coherencia(c)
        try:
            fig = capturar(c); mal = defectos(fig); plt.close(fig)
            if SALIDA: de.draw_unifilar_generico(c, os.path.join(SALIDA, "texto_" + str(abs(hash(texto)) % 1000) + ".png"))
            chk(not mal, f"texto -> dibujo sin textos superpuestos: {texto[:50]}... {mal[:3] if mal else ''}")
        except Exception as ex:
            chk(False, f"texto -> dibujo lanzo {type(ex).__name__}: {ex}")

    # ---- trafo COMPARTIDO con gabinete en el renderer generico (directa/semidirecta, con/sin respaldo) ----
    # El recinto punteado no debe cruzar rotulos ni circulos, ni invadir el cuadro de datos
    # (se encontro con este detector: "ESTE MEDIDOR", "+ otros medidores", "GABINETE COMPARTIDO", MEDIDOR...).
    import bot
    for tipo_, resp_, gab_, nus_ in itertools.product(("directa", "semidirecta"), (False, True), (True, False), ("", "6")):
        c = bot._verificar_coherencia(dict(
            DEFAULT, salida="unifilar", sistema="tri4h", tipo=tipo_, norma="RA8", instalacion="trafo", trafo_uso="compartido",
            trafo_gabinete=gab_, trafo_n_usuarios=nus_, trafo_tipo="trifasico", trafo_kva="150", v_mt="13.2 kV", respaldo=resp_,
            proteccion_antes="100 A", rel_tc="200/5" if tipo_ != "directa" else ""))[0]
        fig = capturar(c); mal = defectos(fig)
        # el recinto debe quedar DENTRO del lienzo (con xc=22 el de respaldo se recortaba por la izquierda)
        ax_ = fig.axes[0]; x0_ax = ax_.get_xlim()[0]
        recintos = [pt for pt in ax_.patches if type(pt).__name__ == "FancyBboxPatch"
                    and pt.get_edgecolor()[:3] == (0x8a / 255, 0x4b / 255, 0.0) and pt.get_width() < 0.9 * (ax_.get_xlim()[1] - x0_ax)]
        recortado = [pt for pt in recintos if pt.get_x() < x0_ax]
        plt.close(fig)
        chk(not mal and not recortado,
            f"compartido generico: {tipo_:11s} respaldo={resp_!s:5} gabinete={gab_!s:5} n={nus_!r:3} sin textos pisados ni recinto recortado {mal[:3] if mal else ''}")

    # ---- escenarios: dibujan, no pisan textos, y se dejan en disco para revisarlos ----
    for nombre, cfg in ESCENARIOS.items():
        try:
            fig = capturar(cfg)
        except Exception as e:
            chk(False, f"{nombre}: lanzo {type(e).__name__}: {e}"); continue
        mal = defectos(fig)
        if SALIDA:
            os.makedirs(SALIDA, exist_ok=True)
            de.draw_unifilar_generico(cfg, os.path.join(SALIDA, nombre + ".png"))
        plt.close(fig)
        chk(not mal, f"{nombre}: sin textos superpuestos {mal[:4] if mal else ''}")

    print("\nRESULTADO:", "TODO OK" if not malos_tot else f"{malos_tot} fallos")
    return malos_tot

if __name__ == "__main__":
    sys.exit(1 if main() else 0)
