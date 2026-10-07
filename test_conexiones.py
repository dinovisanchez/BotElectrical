#!/usr/bin/env python3
"""Diagrama de CONEXIONES: pruebas geometricas sobre lo que realmente se dibuja.

Que un diagrama "corra sin excepcion" no prueba que sea legible: el usuario reporto que el
de conexiones "no esta bien" y las causas eran visuales (conductores de fases distintas
dibujados uno ENCIMA de otro -> parecian empalmados; un neutro continuo que parecia puentear
el medidor...). Aqui se recogen las lineas del grafico y se comprueba que:
  1. dos conductores distintos nunca comparten un tramo colineal (se taparian entre si);
  2. el cableado cumple las reglas confirmadas: "in" -> borne DERECHO del bloque, "cierre" ->
     IZQUIERDO, y el secundario de cada TC tiene sus DOS salidas conectadas;
  3. la tension de un TP sale de su secundario / barra BN (no de la linea primaria), y esa barra
     existe y esta a tierra.
Reglas de trabajo del repo: "energiza" el diagrama, ningun elemento puede tapar a otro."""
import sys, os, logging, itertools, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
logging.disable(logging.CRITICAL)
from parser import DEFAULT

QUIET = os.environ.get("QUIET")
import tempfile
TMP = os.path.join(tempfile.gettempdir(), "_cx_test.png")
XL, XR = 81.0, 99.0        # bornes izquierdo / derecho del bloque de pruebas (bx0=76, bx1=104)


def cargar(path=None):
    """El modulo del motor (o una copia vieja, para comprobar que la prueba SI detecta el bug)."""
    if path is None:
        import diagram_engine as m; return m
    spec = importlib.util.spec_from_file_location("motor_alterno", path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def dibujar(motor, cfg):
    """Dibuja `cfg` y devuelve las lineas (Line2D) del eje, capturando la figura antes de que
    el motor la cierre."""
    capt = []
    cierre = plt.close
    plt.close = lambda fig=None: capt.append(fig)      # el motor llama plt.close(fig) al final
    try:
        motor.draw_conexiones_retie(cfg, TMP)
    finally:
        plt.close = cierre
    fig = capt[-1]
    lineas = list(fig.axes[0].lines)
    cierre(fig)
    return lineas


def segmentos(linea):
    """Tramos horizontales/verticales de una polilinea: [(orient, fijo, a, b)]."""
    xs, ys = list(linea.get_xdata()), list(linea.get_ydata())
    out = []
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if abs(y0 - y1) < 1e-6 and abs(x0 - x1) > 0.3:
            out.append(("h", round(y0, 2), min(x0, x1), max(x0, x1)))
        elif abs(x0 - x1) < 1e-6 and abs(y0 - y1) > 0.3:
            out.append(("v", round(x0, 2), min(y0, y1), max(y0, y1)))
    return out


def solapes(lineas, x_max=None):
    """Pares de conductores DISTINTOS con un tramo colineal en comun (uno tapa al otro)."""
    segs = []
    for i, l in enumerate(lineas):
        for s in segmentos(l):
            if x_max is not None and (s[0] == "h" and s[3] > x_max or s[0] == "v" and s[1] > x_max):
                continue
            segs.append((i, s))
    malos = []
    for (i, a), (j, b) in itertools.combinations(segs, 2):
        if i == j or a[0] != b[0] or abs(a[1] - b[1]) > 0.05:
            continue
        comun = min(a[3], b[3]) - max(a[2], b[2])
        if comun > 0.3:
            malos.append((a[0], a[1], round(max(a[2], b[2]), 1), round(min(a[3], b[3]), 1)))
    return sorted(set(malos))


def cfg_de(**kw):
    return dict(DEFAULT, salida="conexiones", **kw)


def main(motor_path=None):
    motor = cargar(motor_path)
    malos = 0
    def chk(cond, msg):
        nonlocal malos; malos += not cond
        if not QUIET: print("OK  " if cond else "MAL ", msg)

    # ---- 1) ningun conductor tapa a otro ----
    # Semidirecta / indirecta: se revisa el panel izquierdo (TC, TP, tensiones, rieles: x < 60).
    # Directa: se revisa TODO el dibujo (acometida -> bornera -> carga).
    for sis in ("mono", "bifasico", "tri3h", "tri4h"):
        for tipo in ("semidirecta", "indirecta"):
            if tipo == "semidirecta" and sis == "mono":
                continue
            for norma in ("CENS", "RA8"):
                cfg = cfg_de(sistema=sis, tipo=tipo, norma=norma, rel_tc="200/5", rel_tp="13200/120" if tipo == "indirecta" else "")
                s = solapes(dibujar(motor, cfg), x_max=60)
                chk(not s, f"sin solapes: {tipo:11s} {sis:8s} {norma:4s} {s[:3] if s else ''}")
    for sis in ("mono", "bifasico", "tri4h"):
        for conexion in ("simetrica", "asimetrica"):
            cfg = cfg_de(sistema=sis, tipo="directa", conexion=conexion)
            s = solapes(dibujar(motor, cfg))
            chk(not s, f"sin solapes: directa     {sis:8s} {conexion:10s} {s[:3] if s else ''}")

    # ---- 2) reglas confirmadas: "in" -> borne DERECHO, "cierre" -> IZQUIERDO ----
    def extremos(lineas, x):
        """Cables cuyo ULTIMO punto cae en el borne x del bloque (trazos gruesos de conductor)."""
        return [l for l in lineas if len(l.get_xdata()) >= 4 and abs(l.get_xdata()[-1] - x) < 0.01
                and l.get_linewidth() >= 1.5]
    for sis, n_cur in (("tri4h", 3), ("tri3h", 2), ("bifasico", 2), ("mono", 1)):
        for tipo in ("semidirecta", "indirecta"):
            if tipo == "semidirecta" and sis == "mono":
                continue
            ls = dibujar(motor, cfg_de(sistema=sis, tipo=tipo, rel_tc="200/5", rel_tp="13200/120"))
            izq = [l for l in extremos(ls, XL) if l.get_linewidth() >= 2.0]      # corriente = 2.3
            der = [l for l in extremos(ls, XR) if l.get_linewidth() >= 2.0]
            chk(len(izq) == n_cur, f"cierres -> borne izquierdo ({tipo}, {sis}): {len(izq)} de {n_cur} secundarios conectados")
            chk(len(der) == n_cur, f"'in'    -> borne derecho   ({tipo}, {sis}): {len(der)} de {n_cur}")

    # ---- 3) indirecta: tension desde el secundario del TP, barra BN y tierra ----
    for sis in ("tri4h", "tri3h", "bifasico", "mono"):
        ls = dibujar(motor, cfg_de(sistema=sis, tipo="indirecta", rel_tc="50/5", rel_tp="13200/120"))
        # barra BN: un trazo horizontal punteado largo, en la franja de los TP (x < 60), de la que
        # ARRANCA (primer punto) el cable de referencia del medidor. La linea de neutro tambien es
        # punteada y larga, pero de ella no arranca ningun cable de la acometida: asi se distingue.
        cand = [(s, l) for l in ls for s in segmentos(l)
                if s[0] == "h" and s[3] - s[2] > 3 and l.get_linestyle() == "--" and s[3] < 60]
        def arranca_de(s_, l_):
            _, y_, xa_, xb_ = s_
            return any(abs(m.get_ydata()[0] - y_) < 0.01 and xa_ - 0.01 <= m.get_xdata()[0] <= xb_ + 0.01
                       and len(m.get_xdata()) >= 4 for m in ls if m is not l_)
        chk(any(arranca_de(s_, l_) for s_, l_ in cand),
            f"TP ({sis}): existe la barra BN y la referencia del medidor sale de ella (no de la linea primaria)")
        # puesta a tierra de la barra: un trazo verde corto que cuelga de la barra
        verdes = [l for l in ls if l.get_color() == "#2E7D32"]
        chk(verdes, f"TP ({sis}): la barra BN tiene puesta a tierra")

    print("\nRESULTADO:", "TODO OK" if not malos else f"{malos} fallos")
    return malos


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1] if len(sys.argv) > 1 else None) else 0)
