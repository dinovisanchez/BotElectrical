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


def defectos(fig):
    """[(texto, otro)] con cajas de texto que se pisan entre si o que cruza un cable."""
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    ax = fig.axes[0]
    cajas = []
    for t in ax.texts:
        if not t.get_visible() or not t.get_text().strip(): continue
        b = t.get_window_extent(rend)
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
