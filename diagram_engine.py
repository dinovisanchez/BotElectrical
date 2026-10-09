# -*- coding: utf-8 -*-
"""
Motor de diagramas para sistemas de medida de energia.
  draw(cfg, out)                 -> diagrama de CONEXIONES (Medidor <-> Bloque <-> TC/TP)
  draw_unifilar(cfg, out)        -> diagrama UNIFILAR tecnico de la medida
  draw_unifilar_tablero(cfg, out)-> unifilar de TABLERO GENERAL BT (acometida/trafo
                                     + interruptor ppal + barra + ramales de salida)

cfg:
  sistema : 'mono'|'bifasico'|'tri3h'(2 elem)|'tri4h'(3 elem)
  tipo    : 'directa'|'semidirecta'|'indirecta'
  respaldo: bool
  norma   : 'CENS'|'RA8'
  rel_tc, rel_tp, proyecto, tension : str
Colores: R rojo, S azul, T amarillo, N gris, tierra verde.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, FancyBboxPatch, Arc, Polygon
from matplotlib.lines import Line2D
import numpy as np
import math, re, textwrap

COL = {"R": "#D32F2F", "S": "#1565C0", "T": "#F9A825", "N": "#5A5A5A", "G": "#2E7D32"}
INK = "#1F2A37"

# ---------- definicion de terminales del medidor ----------
def meter_terminals(sistema, norma):
    """
    Orden REAL de la bornera del medidor (confirmado por el usuario):

    3 elementos (tri4h):
      1=I-R(corriente R, viene del borne DERECHO del bloque - salida hacia carga)
      2=V-R (tension R, viene del secundario TP-R)
      3=Cierre-R (viene del borne IZQUIERDO del bloque - entrada de corriente)
      4=I-S, 5=V-S, 6=Cierre-S  (idem para fase S)
      7=I-T, 8=V-T, 9=Cierre-T  (idem para fase T)
      11=N (neutro, secundario b/n de los TPs -> BN)

    2 elementos Aron (tri3h) - indirecta trifasica con 2TC y 2TP:
      1=I-R  2=V-R  3=Cierre-R  (fase R)
      4=Cierre-T (los 2 cierres del bloque llegan aqui, o puenteados)
      5=N
      6=I-T  7=V-T  8=Cierre-T  (fase T)
      Puente interno en medidor: 3-6-9 (borneras de cierre puenteadas entre si)
      Nota: el bloque puede enviar 2 lineas a bornera 4, o puentearlas en el bloque

    Cada tupla: (num_bornera, etiqueta, tipo, fase, rol)
      tipo: "I"=corriente, "V"=tension
      rol:  "in"=entrada corriente(borne der bloque->carga),
            "cierre"=entrada cierre(borne izq bloque),
            "puente"=bornera puenteada internamente (no requiere cable propio),
            None=tension
    """
    if sistema == "mono":
        return [("1","IA","I","R","in"),
                ("2","VA","V","R",None),
                ("3","Cierre","I","R","cierre"),
                ("4","N","V","N",None)]

    if sistema == "bifasico":
        return [("1","IA","I","R","in"),
                ("2","VA","V","R",None),
                ("3","Cierre-R","I","R","cierre"),
                ("4","IB","I","S","in"),
                ("5","VB","V","S",None),
                ("6","Cierre-S","I","S","cierre"),
                ("7","N","V","N",None)]

    if sistema == "tri3h":
        # C1(3) va al bloque como cierre normal desde TC-R
        # El puente C1->C2 en la bornera y el cable al borne 4 se manejan aparte
        # C2(6), C3(9) sin cable al medidor
        return [("2","VA","V","R",None),
                ("8","VC","V","T",None),
                ("5","N","V","N",None),
                ("3","C1","I","R","cierre"),
                ("1","I1","I","R","in"),
                ("6","C2","I","T","puente_3"),
                ("7","I2","I","T","in"),
                ("9","C3","I","R","puente_3")]

    # tri4h: 3 elementos, orden real del bloque de pruebas:
    # V1, V2, V3, N, C1, I1, C2, I2, C3, I3
    return [("2","VA","V","R",None),
            ("5","VB","V","S",None),
            ("8","VC","V","T",None),
            ("11","N","V","N",None),
            ("3","Cierre-R","I","R","cierre"),
            ("1","IA","I","R","in"),
            ("6","Cierre-S","I","S","cierre"),
            ("4","IB","I","S","in"),
            ("9","Cierre-T","I","T","cierre"),
            ("7","IC","I","T","in")]

def meter_bridges(sistema):
    """
    Puentes INTERNOS en la bornera del medidor.
    tri3h (Aron): borneras 3, 8 y 9 se puentean entre si dentro del medidor.
    Con respaldo Aron:
      - B3 bloque -> B1 medidor RESPALDO  (cable externo, se maneja en ruteo)
      - borne 4 RESPALDO -> borne 6 PRINCIPAL (cable externo, se maneja en ruteo)
    """
    if sistema == "tri3h":
        # Puentes internos: 3 <-> 6 <-> 9
        return [("3", ["6", "9"])]
    return []

def phases_of(s):
    return {"mono":["R"],"bifasico":["R","S"],"tri3h":["R","S","T"],"tri4h":["R","S","T"]}[s]

def current_phases(s):
    return {"mono":["R"],"bifasico":["R","S"],"tri3h":["R","T"],"tri4h":["R","S","T"]}[s]

SIS_TXT = {"mono":"MONOFASICA","bifasico":"BIFASICA",
           "tri3h":"TRIFASICA 3 HILOS (2 elementos)","tri4h":"TRIFASICA 4 HILOS (3 elementos)"}

# ---------- simbolos ----------
def _ct(ax, x, y, color, label):
    """Transformador de corriente: dos circulos sobre la linea de fase."""
    ax.add_patch(Circle((x-0.85,y),1.35,fill=False,ec=color,lw=2.0,zorder=5))
    ax.add_patch(Circle((x+0.85,y),1.35,fill=False,ec=color,lw=2.0,zorder=5))
    ax.add_patch(Circle((x-0.85,y+1.35),0.28,fc=color,ec=color,zorder=6))  # polaridad
    ax.text(x,y+2.9,label,ha="center",va="bottom",fontsize=8.5,color=color,fontweight="bold")

def _pt(ax, x, y_fase, y_ret, color, label, y_bus):
    """TP del diagrama de conexiones. Cuelga justo DEBAJO de su linea de fase, dentro de
    su propia franja (antes los circulos caian sobre la linea de la fase de abajo):
      - arriba el devanado PRIMARIO: baja desde la fase y VUELVE por la izquierda a la
        linea `y_ret` (neutro; en el TP de 2 elementos, la fase S). Los puntos negros son
        los empalmes reales: un cruce SIN punto no es conexion;
      - abajo el SECUNDARIO con sus dos terminales: 'a' a la derecha (hacia el medidor) y
        'b' hacia abajo (comun de los secundarios, barra BN en `y_bus`).
    Antes el cable de tension del medidor salia de la linea PRIMARIA, como si el TP no
    estuviera en el circuito. Devuelve ((x_a, y_a), (x_b, y_b))."""
    r = 1.25
    yp, ys = y_fase - 3.0, y_fase - 5.0
    xr = x - 2.0
    ax.plot([x, x], [y_fase, yp + r], color=color, lw=1.7, zorder=4)
    ax.add_patch(Circle((x, yp), r, fill=False, ec=color, lw=1.8, zorder=5))
    ax.add_patch(Circle((x, ys), r, fill=False, ec=color, lw=1.8, zorder=5))
    ax.plot([x - r, xr, xr], [yp, yp, y_ret], color=color, lw=1.7, zorder=4)   # retorno del primario
    for px, py in ((x, y_fase), (xr, y_ret)):
        ax.add_patch(Circle((px, py), 0.45, fc=color, ec=color, zorder=6))
    ax.plot([x, x], [ys - r, y_bus], color=COL["N"], lw=1.7, ls=(0, (6, 3)), zorder=3)   # 'b'
    ax.plot([x + r, x + 2.3], [ys, ys], color=color, lw=1.7, zorder=4)                  # 'a'
    ax.text(x + 1.7, yp, label, ha="left", va="center", fontsize=7.5, color=color, fontweight="bold")
    return (x + 2.3, ys), (x, y_bus)

def _ground(ax, x, y, s=1.0):
    ax.plot([x,x],[y,y-1.2*s],color=COL["G"],lw=1.4)
    for i,w in enumerate([2.0,1.3,0.7]):
        ax.plot([x-w*s,x+w*s],[y-(1.2+0.5*i)*s]*2,color=COL["G"],lw=1.4)

# ============================================================
#  SIMBOLOS IEC 60617 (para unifilar)
# ============================================================
def _u_breaker(ax,x,y,c=INK,s=1.0):
    """Interruptor automatico: cuadrado sobre la linea."""
    ax.add_patch(Rectangle((x-1.7*s,y-1.9*s),3.4*s,3.8*s,fill=False,ec=c,lw=2.2,zorder=4))

def _u_disc(ax,x,y,c=INK,s=1.0,tierra=False):
    """Seccionador: cuchilla abierta con pivote. Si tierra=True, agrega una
    cuchilla de puesta a tierra integrada (ramal lateral verde) -- el
    seccionador unico de la jerarquia del unifilar la lleva siempre."""
    ax.add_patch(Circle((x,y-2.0*s),0.4,fc=c,ec=c,zorder=5))
    ax.add_patch(Circle((x,y+2.0*s),0.4,fc=c,ec=c,zorder=5))
    ax.plot([x,x+2.3*s],[y-2.0*s,y+1.6*s],color=c,lw=2.2,zorder=4)
    if tierra:
        gx = x + 2.6*s
        ax.plot([x,gx],[y,y],color=COL["G"],lw=1.1,zorder=3)
        _ground(ax, gx, y, 0.4*s)

def _u_fuse(ax,x,y,c=INK,s=1.0):
    """Cortacircuitos fusible: rectangulo con barra."""
    ax.add_patch(Rectangle((x-1.1*s,y-2.2*s),2.2*s,4.4*s,fill=False,ec=c,lw=2,zorder=4))
    ax.plot([x,x],[y-2.2*s,y+2.2*s],color=c,lw=1.5,zorder=4)

def _u_arrester(ax,x,y,c=COL["G"],s=1.0):
    """Pararrayos / DPS: rectangulo con flecha a tierra."""
    ax.add_patch(Rectangle((x-1.3*s,y-2.1*s),2.6*s,4.2*s,fill=False,ec=c,lw=1.9,zorder=4))
    ax.annotate("",xy=(x,y-1.5*s),xytext=(x,y+1.5*s),
                arrowprops=dict(arrowstyle="-|>",color=c,lw=1.7))
    _ground(ax,x,y-2.1*s,0.55)

def _u_ct(ax,x,y,c=COL["R"],s=1.0):
    """TC: anillo sobre la linea."""
    ax.add_patch(Circle((x,y),2.1*s,fill=False,ec=c,lw=2.2,zorder=4))

def _u_vt(ax,x,y,c=COL["S"],s=1.0,ground=True):
    """TP: dos circulos verticales (+ tierra opcional)."""
    ax.add_patch(Circle((x,y+1.1*s),1.25*s,fill=False,ec=c,lw=1.9,zorder=4))
    ax.add_patch(Circle((x,y-1.1*s),1.25*s,fill=False,ec=c,lw=1.9,zorder=4))
    if ground: _ground(ax,x,y-2.4*s,0.55)

def _u_xfmr(ax,x,y,c=INK,s=1.0,ground=True):
    """Transformador de potencia: dos circulos entrelazados + tierra en neutro secundario."""
    ax.add_patch(Circle((x,y+1.5*s),2.2*s,fill=False,ec=c,lw=2.2,zorder=4))
    ax.add_patch(Circle((x,y-1.5*s),2.2*s,fill=False,ec=c,lw=2.2,zorder=4))
    if ground:
        _ground(ax, x, y-3.7*s, 0.5*s)

def _u_relay(ax,x,y,c="#6A1B9A",funcs="50/51",s=1.0):
    """Rele de proteccion: circulo con funciones ANSI."""
    ax.add_patch(Circle((x,y),2.6*s,fill=False,ec=c,lw=2,zorder=4))
    ax.text(x,y,funcs,ha="center",va="center",fontsize=6.8,color=c,fontweight="bold",zorder=5)

def _u_meter(ax, x, y, r=8.0, fontsize=8, lw=1.8, label_below=None, label_fontsize=6.3,
             label_dx=0.0, label_ha="center"):
    """Medidor de energia (kWh): circulo doble -- convencion IEC 60617 para
    instrumento INTEGRADOR (distinta de un instrumento simple, que se
    representa con un solo circulo). Es la unica funcion que dibuja este
    simbolo -- la usan tanto el cuerpo del diagrama como el plano de
    simbologia, para que nunca queden desincronizados entre si (antes el
    plano de simbologia tenia un icono viejo -- caja oscura -- que ya no
    coincidia con el medidor real dibujado en el unifilar). Sigue siendo
    flat/vector, sin degradados ni sombras (Convenciones fijas)."""
    ax.add_patch(Circle((x, y), r, fill=True, fc="white", ec=INK, lw=lw, zorder=3))
    ax.add_patch(Circle((x, y), r * 0.74, fill=False, ec=INK, lw=max(0.6, lw * 0.5), zorder=4))
    ax.text(x, y, "kWh", ha="center", va="center",
            fontsize=fontsize, fontweight="bold", color=INK, family="monospace", zorder=5)
    if label_below:
        # label_dx/label_ha: cuando el conductor CONTINUA hacia abajo (medida
        # directa en linea) el rotulo centrado queda tachado por la linea; se
        # corre a un lado (ha="left"/"right" + dx) para que quede junto a ella.
        ax.text(x + label_dx, y - r - 2.2, label_below, ha=label_ha, va="top",
                fontsize=label_fontsize, color="#555", fontweight="bold")

def _u_bloque_prueba(ax, x0, y0, w, h, linea1="", linea2=""):
    """Bloque de pruebas: rectangulo blanco de borde fino, sin degradados
    azules ni esquinas redondeadas (Convenciones fijas). Unica funcion que
    lo dibuja -- igual que _u_meter, la usan el cuerpo del diagrama y el
    plano de simbologia para no desincronizarse."""
    ax.add_patch(Rectangle((x0, y0), w, h, fill=True, fc="white", ec=INK, lw=1.3, zorder=3))
    if linea1:
        ax.text(x0 + w / 2, y0 + h - 3, linea1, ha="center", va="center",
                fontsize=6.6, fontweight="bold", color=INK)
    if linea2:
        ax.text(x0 + w / 2, y0 + 3, linea2, ha="center", va="center",
                fontsize=7.5, fontweight="bold", color=INK)

# ============================================================
#  DIAGRAMA DE CONEXIONES (version RETIE)
#   - DIRECTA: esquema de bornera con lineas internas
#              simetricas (espejo) o asimetricas (cruzadas)
#   - SEMI/INDIRECTA: ACOMETIDA -> TC/TP -> BLOQUE DE PRUEBA
#              -> MEDIDOR -> CARGA (con seccionador si aplica)
# ============================================================
def draw_conexiones_retie(cfg, out_path):
    tipo = cfg.get("tipo", "directa")
    if tipo == "directa":
        return _draw_directa_retie(cfg, out_path)
    return _draw_semi_indirecta_retie(cfg, out_path)


def _draw_directa_retie(cfg, out_path):
    """
    Medida DIRECTA — estilo fisico con bornera global numerada.
    Simetrica : bornes entrada en la mitad izquierda, salidas en la derecha (espejo).
    Asimetrica: pares adyacentes entrada-salida por conductor (secuencial).
    """
    sistema  = cfg.get("sistema", "tri4h")
    norma    = cfg.get("norma",   "RA8")
    conexion = cfg.get("conexion","simetrica")
    respaldo = bool(cfg.get("respaldo", False))

    sis_lbl = {"mono":"MONOFASICA","bifasico":"BIFASICA",
               "tri3h":"TRIFASICA 3 HILOS","tri4h":"TRIFASICA 4 HILOS"}[sistema]

    # ── Bornera global: (conductor, etiqueta, 'ent'|'sal') por posicion ────
    if sistema == "mono":
        if conexion == "simetrica":
            layout = [("R","F-ent","ent"),("N","N-sal","sal"),
                      ("N","N-ent","ent"),("R","F-sal","sal")]
        else:
            layout = [("R","F-ent","ent"),("R","F-sal","sal"),
                      ("N","N-ent","ent"),("N","N-sal","sal")]
    elif sistema == "bifasico":
        if conexion == "simetrica":
            layout = [("R","R-ent","ent"),("S","S-ent","ent"),("N","N-ent","ent"),
                      ("N","N-sal","sal"),("S","S-sal","sal"),("R","R-sal","sal")]
        else:
            layout = [("R","R-ent","ent"),("R","R-sal","sal"),
                      ("S","S-ent","ent"),("S","S-sal","sal"),
                      ("N","N-ent","ent"),("N","N-sal","sal")]
    else:  # tri4h  (tri3h usa este bloque tb, sin neutro fisico)
        if conexion == "simetrica":
            layout = [("R","R-ent","ent"),("S","S-ent","ent"),("T","T-ent","ent"),("N","N-ent","ent"),
                      ("N","N-sal","sal"),("T","T-sal","sal"),("S","S-sal","sal"),("R","R-sal","sal")]
        else:
            layout = [("R","R-ent","ent"),("R","R-sal","sal"),
                      ("S","S-ent","ent"),("S","S-sal","sal"),
                      ("T","T-ent","ent"),("T","T-sal","sal"),
                      ("N","N-ent","ent"),("N","N-sal","sal")]

    n_bornes  = len(layout)
    # Conductores unicos en orden de aparicion
    seen = {}
    for cond,_,_ in layout:
        if cond not in seen: seen[cond] = True
    conductores = list(seen.keys())   # e.g. ['R','S','T','N']

    # Indices de borne (0-based) para entrada y salida de cada conductor
    ent_idx = {}; sal_idx = {}
    for i,(cond,_,side) in enumerate(layout):
        if side == "ent": ent_idx[cond] = i
        else:             sal_idx[cond] = i

    # ── Canvas ─────────────────────────────────────────────────────────────
    BPITCH   = 17          # separacion entre bornes
    LEFT_M   = 45          # margen izquierdo (labels acometida)
    RIGHT_M  = 45          # margen derecho (labels carga)
    BORN_PAD = 10          # padding interno del medidor a cada lado
    W = LEFT_M + RIGHT_M + BORN_PAD*2 + BPITCH * n_bornes
    W = max(W, 180)

    N_COND   = len(conductores)
    LANE_SEP = 10          # separacion entre lanes de conductor
    HDR_H    = 14          # cabecera (titulos)
    n_coil_conds = sum(1 for c in conductores if c != "N")
    MED_H    = max(55, n_coil_conds * 22 + 14)   # altura dinamica: espacio para coils apilados
    BOT_H    = N_COND * LANE_SEP + 12   # lanes de conductor + nota
    H        = HDR_H + MED_H + BOT_H

    fig, ax = plt.subplots(figsize=(W/9.5, H/9.5))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    # ── Titulos ────────────────────────────────────────────────────────────
    ax.text(W/2, H-2, f"DIAGRAMA DE CONEXIONES  ·  MEDIDA DIRECTA  ·  {sis_lbl}",
            ha="center", fontsize=9.5, fontweight="bold", color=INK)
    sub = f"Norma {norma}  ·  Conexion {conexion.upper()}"
    if respaldo: sub += "  ·  PRINCIPAL + RESPALDO"
    ax.text(W/2, H-5.5, sub, ha="center", fontsize=8, color="#666")

    # ── Coordenadas de bornes ──────────────────────────────────────────────
    BORN_R   = 4.5         # radio circulo borne
    BORN_Y   = BOT_H + 7  # y del centro de los bornes
    bx_start = LEFT_M + BORN_PAD + BPITCH * 0.5
    bx       = [bx_start + i * BPITCH for i in range(n_bornes)]

    # ── Medidor box ────────────────────────────────────────────────────────
    MX0 = bx[0]  - BORN_PAD - BORN_R
    MX1 = bx[-1] + BORN_PAD + BORN_R
    MY0 = BORN_Y - BORN_R - 1
    MY1 = MY0 + MED_H
    ax.add_patch(Rectangle((MX0, MY0), MX1-MX0, MY1-MY0,
                 fill=False, ec="#444", lw=1.5, ls=(0,(4,3)), zorder=1))
    ax.text((MX0+MX1)/2, MY1 + 2, "MEDIDOR",
            ha="center", va="bottom", fontsize=9, fontweight="bold", color="#333")

    # ── Bornera (fondo gris) ───────────────────────────────────────────────
    ax.add_patch(Rectangle((MX0+2, BORN_Y-BORN_R-2), MX1-MX0-4, 2*BORN_R+5,
                 fill=True, fc="#EEEEEE", ec="#888", lw=0.8, zorder=2))
    ax.text((MX0+MX1)/2, BORN_Y - BORN_R - 3.5, "BORNERA",
            ha="center", va="top", fontsize=6, color="#999")

    # ── Bornes numerados ───────────────────────────────────────────────────
    for i,(cond,lbl,side) in enumerate(layout):
        c = COL.get(cond, "#333")
        ax.add_patch(Circle((bx[i], BORN_Y), BORN_R,
                     fill=True, fc="white", ec=c, lw=1.8, zorder=5))
        ax.text(bx[i], BORN_Y, str(i+1),
                ha="center", va="center", fontsize=6.5, fontweight="bold",
                color="#222", zorder=6)
        # a la derecha del cable que baja del borne: centrado, el conductor lo tachaba
        ax.text(bx[i] + 1.0, BORN_Y - BORN_R - 2.6, lbl,
                ha="left", va="top", fontsize=5.5, color=c, zorder=5)

    # ── Lanes de conductores (debajo del medidor) ──────────────────────────
    LANE_Y_TOP = BORN_Y - BORN_R - 10  # primera lane justo bajo la bornera
    lane_y = {}
    for ki, cond in enumerate(conductores):
        lane_y[cond] = LANE_Y_TOP - ki * LANE_SEP

    X_ACO = 8    # x inicio lineas acometida
    X_CAR = W-8  # x fin lineas carga
    lane_y_out = {}
    for cond in conductores:
        ei_, si_ = ent_idx.get(cond), sal_idx.get(cond)
        cruza = ei_ is not None and si_ is not None and si_ < ei_
        lane_y_out[cond] = lane_y[cond] + (4 if cruza else 0)

    for cond in conductores:
        c  = COL.get(cond, "#333")
        ly = lane_y[cond]
        lw = 2.2 if cond != "N" else 1.8
        ls = "-" if cond != "N" else (0,(5,2))
        lbl = "Neutro" if cond == "N" else f"Fase {cond}"

        # Etiquetas
        ax.text(X_ACO - 1, ly, lbl, ha="right", va="center",
                fontsize=8.5, fontweight="bold", color=c)
        ly_out = lane_y_out[cond]
        ax.text(X_CAR + 1, ly_out, lbl, ha="left", va="center",
                fontsize=8.5, fontweight="bold", color=c)

        ei = ent_idx.get(cond)
        si = sal_idx.get(cond)
        ex = bx[ei] if ei is not None else None
        sx = bx[si] if si is not None else None

        # Acometida → borne entrada
        if ex is not None:
            ax.plot([X_ACO, ex], [ly, ly], color=c, lw=lw, ls=ls, zorder=2)
            ax.plot([ex, ex],    [ly, BORN_Y - BORN_R], color=c, lw=lw, ls=ls, zorder=2)

        # Borne salida → carga
        if sx is not None:
            ax.plot([sx, sx],    [BORN_Y - BORN_R, ly_out], color=c, lw=lw, ls=ls, zorder=2)
            ax.plot([sx, X_CAR], [ly_out, ly_out], color=c, lw=lw, ls=ls, zorder=2)

    # Buses verticales acometida y carga
    ys_all = list(lane_y.values()) + list(lane_y_out.values())
    bus_top = max(ys_all) + 2; bus_bot = min(ys_all) - 2
    ax.plot([X_ACO, X_ACO], [bus_bot, bus_top], color="#AAA", lw=0.7, zorder=1)
    ax.plot([X_CAR, X_CAR], [bus_bot, bus_top], color="#AAA", lw=0.7, zorder=1)
    # Rotulos ARRIBA de cada barra (no girados a su lado: compartian x con los rotulos de
    # fase/neutro y, al bajar la linea de carga del neutro, se pisaban)
    ax.text(X_ACO, bus_top+1.0, "ACOMETIDA", ha="center", va="bottom", fontsize=7, color="#555")
    ax.text(X_CAR, bus_top+1.0, "CARGA",     ha="center", va="bottom", fontsize=7, color="#555")

    # ── Bobinas I — una por fase, apiladas verticalmente ────────────────────
    COIL_R = 6.5
    # el borde de cada bobina queda DENTRO de la caja (antes la de arriba cruzaba el
    # borde punteado) y por encima del rotulo "V+" de la derivacion de tension
    coil_zone_bot = BORN_Y + BORN_R + COIL_R + 8
    coil_zone_top = MY1 - 3 - COIL_R
    coil_zone_h   = coil_zone_top - coil_zone_bot

    coil_conds = [c for c in conductores if c != "N"]
    n_coils    = len(coil_conds)
    # y-positions evenly spaced: highest coil for first conductor
    if n_coils == 1:
        coil_ys = [coil_zone_bot + coil_zone_h * 0.5]
    else:
        coil_ys = [coil_zone_bot + coil_zone_h * (n_coils - 1 - ki) / (n_coils - 1)
                   for ki in range(n_coils)]

    for ki, cond in enumerate(coil_conds):
        c    = COL.get(cond, "#333")
        ei   = ent_idx.get(cond)
        si   = sal_idx.get(cond)
        if ei is None or si is None: continue
        ex_b = bx[ei]; sx_b = bx[si]
        cy   = coil_ys[ki]

        if conexion == "simetrica":
            # Coil queda sobre el borne de entrada; la salida cruza con cable horizontal largo
            cx = ex_b + COIL_R      # borde izq del coil alineado con borne
        else:
            # Coil centrado entre el par adyacente de bornes
            cx = (ex_b + sx_b) / 2.0

        # Circulo bobina I
        ax.add_patch(Circle((cx, cy), COIL_R,
                     fill=True, fc="#FFFDE7", ec=c, lw=1.8, zorder=3))
        ax.text(cx, cy, "I", ha="center", va="center",
                fontsize=8.5, fontweight="bold", color=c, zorder=4)

        # Cable borne-entrada → coil (entra por el lado izquierdo del circulo)
        ax.plot([ex_b, ex_b], [BORN_Y + BORN_R, cy], color=c, lw=1.8, zorder=2)
        # solo tramo horizontal si el borne no está alineado con el borde izq del coil
        if abs(ex_b - (cx - COIL_R)) > 0.5:
            ax.plot([ex_b, cx - COIL_R], [cy, cy], color=c, lw=1.8, zorder=2)

        # Cable coil (lado derecho) → borne-salida → abajo
        ax.plot([cx + COIL_R, sx_b], [cy, cy], color=c, lw=1.8, zorder=2)
        ax.plot([sx_b, sx_b], [cy, BORN_Y + BORN_R], color=c, lw=1.8, zorder=2)

        # Tap de tension V+
        tap_bx = ex_b if conexion == "simetrica" else sx_b
        tap_y  = BORN_Y + BORN_R + 3
        # (antes habia aqui una linea punteada hasta la bobina: iba EXACTAMENTE encima del
        # cable de fase, asi que no se veia y solo duplicaba el trazo; basta el punto "V+")
        ax.add_patch(Circle((tap_bx, tap_y), 1.6, fc=c, ec=c, zorder=7))
        ax.text(tap_bx + 2, tap_y + 1.5, "V+", ha="left", va="bottom",
                fontsize=5, color=c)

    # ── Neutro dentro del medidor (pass-through) ────────────────────────────
    n_ei = ent_idx.get("N"); n_si = sal_idx.get("N")
    if n_ei is not None and n_si is not None:
        nx_e = bx[n_ei]; nx_s = bx[n_si]
        N_Y  = MY0 + (MY1-MY0) * 0.25
        ax.plot([nx_e, nx_e, nx_s, nx_s],
                [BORN_Y+BORN_R, N_Y, N_Y, BORN_Y+BORN_R],
                color=COL["N"], lw=1.5, ls=(0,(4,2)), zorder=2)
        ax.text((nx_e+nx_s)/2, N_Y + 1.5, "N", ha="center", va="bottom",
                fontsize=7, color=COL["N"])

    # ── Nota bornera ───────────────────────────────────────────────────────
    partes = [f"{i+1}:{layout[i][1]}" for i in range(n_bornes)]
    if conexion == "simetrica":
        extra = "  ESPEJO — entradas izq, salidas der"
    else:
        extra = "  SECUENCIAL — pares adyacentes ent-sal"
    nota = "Bornera: [" + " | ".join(partes) + "]" + extra
    nota_y = min(ys_all) - 4
    ax.text(W/2, nota_y, nota, ha="center", va="top",
            fontsize=5.8, color="#555", style="italic")

    # Notas de instalacion
    notas_inst = []
    if cfg.get("trafo_kva"):
        notas_inst.append(f"Trafo {cfg.get('trafo_uso','')} {cfg['trafo_kva']} kVA".strip())
    elif cfg.get("instalacion") == "barraje":
        notas_inst.append("Barraje BT")
    if cfg.get("interruptor"):
        notas_inst.append(f"Interruptor {cfg['interruptor']}")
    if notas_inst:
        ax.text(W/2, nota_y - 4, "  ·  ".join(notas_inst),
                ha="center", va="top", fontsize=7, color="#555")

    plt.savefig(out_path, dpi=160, bbox_inches="tight",
                facecolor="white", pad_inches=0.3)
    plt.close(fig)
    return out_path

def _draw_semi_indirecta_retie(cfg, out_path):
    """
    ACOMETIDA -> [TC en serie / TP en paralelo] -> BLOQUE DE PRUEBA
              -> MEDIDOR -> [Seccionador opcional] -> CARGA
    """
    sistema  = cfg.get("sistema","tri4h"); tipo = cfg.get("tipo","indirecta")
    respaldo = bool(cfg.get("respaldo",False)); norma = cfg.get("norma","RA8")
    rel_tc   = cfg.get("rel_tc",""); rel_tp = cfg.get("rel_tp","")
    has_tc   = True   # semidirecta e indirecta siempre tienen TC
    has_tp   = (tipo == "indirecta")

    terms = meter_terminals(sistema, norma); n = len(terms)
    cur_ph = current_phases(sistema); all_ph = phases_of(sistema)

    # Canvas más ancho para respaldo (medidores apilados verticalmente).
    fig_w = 26 if respaldo else 18
    fig_h = 15 if respaldo else 11
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    xlim  = 240 if respaldo else 190
    ylim  = 175 if respaldo else 116
    ax.set_xlim(0, xlim); ax.set_ylim(0, ylim); ax.axis("off")

    titulo = f"DIAGRAMA DE CONEXIONES   ·   MEDIDA {tipo.upper()}   ·   {SIS_TXT[sistema]}"
    if respaldo: titulo += "   ·   PRINCIPAL + RESPALDO"
    ty_titulo = 171 if respaldo else 112
    ty_sub    = 167 if respaldo else 107.5
    ax.text(xlim/2, ty_titulo, titulo, ha="center", va="center",
            fontsize=12 if respaldo else 15, fontweight="bold", color=INK)
    sub = f"Norma {norma}"
    if rel_tc: sub += f"      RTC {rel_tc}"
    if rel_tp: sub += f"      RTP {rel_tp}"
    if cfg.get("calibre_acometida"): sub += f"      Acometida {cfg['calibre_acometida']}"
    if cfg.get("seccionamiento") or cfg.get("interruptor"):
        amp = cfg.get("interruptor") or cfg.get("tc_amp","")
        if amp: sub += f"      Seccionador {amp}" + ("" if "A" in str(amp) else " A")
    ax.text(xlim/2, ty_sub, sub, ha="center", va="center", fontsize=10.5, color="#666")

    # ---------- PRIMARIO (ACOMETIDA) ----------
    base_y = 149 if respaldo else 104
    x0,x1=6,47; dy=8
    y_ph={ph:base_y-i*dy for i,ph in enumerate(all_ph)}
    y_N=base_y-len(all_ph)*dy
    show_N=sistema in ("mono","bifasico","tri4h")
    ax.text((x0+x1)/2,max(y_ph.values())+4.5,"ACOMETIDA",ha="center",fontsize=9,
            color="#444",style="italic")
    for ph in all_ph:
        ax.plot([x0,x1],[y_ph[ph]]*2,color=COL[ph],lw=3,zorder=2)
        ax.text(x0-1.5,y_ph[ph],ph,ha="right",va="center",fontsize=13,fontweight="bold",color=COL[ph])
    if show_N:
        ax.plot([x0,x1],[y_N]*2,color=COL["N"],lw=2.0,ls=(0,(6,3)),zorder=2)
        ax.text(x0-1.5,y_N,"N",ha="right",va="center",fontsize=12,fontweight="bold",color=COL["N"])
    y_low = y_N if show_N else min(y_ph.values())
    y_bus = y_low - 3.2          # barra BN (comun de los secundarios de TP) y de ahi los rieles

    # TC en serie (con la linea de fase, hacia la carga).
    # Sus dos salidas del secundario -- S1 izquierda ("cierre"), S2 derecha ("in") -- salen
    # por ABAJO del circulo y bajan por una columna PROPIA. Antes las tres fases compartian
    # x=tc_x+-1: los conductores se montaban unos sobre otros y parecian empalmados entre
    # fases. La fase de arriba toma la columna mas exterior, asi los codos no se cruzan.
    tc_x=14
    tc_pre, tc_xs = {}, {}
    if has_tc:
        nI = len(cur_ph)
        for k, ph in enumerate(cur_ph):
            y = y_ph[ph]
            _ct(ax, tc_x, y, COL[ph], f"TC-{ph}")
            for lado, dx, xs in (("cierre", -0.85, 8.0 + 1.5*k), ("in", 0.85, 17.0 + 1.2*(nI-1-k))):
                tc_pre[(ph, lado)] = [(tc_x+dx, y-1.35), (tc_x+dx, y-2.7)]
                tc_xs[(ph, lado)] = xs
                ax.add_patch(Circle((tc_x+dx, y-1.35), 0.3, fc=COL[ph], ec=COL[ph], zorder=6))

    # TP en paralelo (fase->neutro).
    # G4: Aron (tri3h) usa solo 2 TP, y en conexion V (linea-linea: R-S y T-S): no hay
    # neutro. CREG 038/2014: medida 2 elementos = 2 TC + 2 TP.
    tp_a, tp_b = {}, {}
    x_ground, x_ntap = 22.6, 24.8
    if has_tp:
        tp_phases = current_phases(sistema) if sistema == "tri3h" else all_ph
        tp_x = {ph: 27 + 7.5*k for k, ph in enumerate(reversed(tp_phases))}   # la de arriba, a la derecha
        for ph in tp_phases:
            if sistema == "tri3h":
                y_fase, y_ret = (y_ph["R"], y_ph["S"]) if ph == "R" else (y_ph["S"], y_ph["T"])
            else:
                y_fase, y_ret = y_ph[ph], y_N
            tp_a[ph], tp_b[ph] = _pt(ax, tp_x[ph], y_fase, y_ret, COL[ph], f"TP-{ph}", y_bus)
        # Barra BN: une los 'b' de los secundarios; va a tierra y de ella sale la referencia
        # (neutro; en el Aron, la fase S) al medidor. Antes ese cable nacia de la linea primaria.
        xs_b = sorted(b_[0] for b_ in tp_b.values())
        ax.plot([x_ground, xs_b[-1]], [y_bus, y_bus], color=COL["N"], lw=1.7, ls=(0,(6,3)), zorder=3)
        for xb in xs_b + [x_ntap]:
            ax.add_patch(Circle((xb, y_bus), 0.45, fc=COL["N"], ec=COL["N"], zorder=6))
        ax.plot([x_ground, x_ground], [y_bus, y_bus-0.8], color=COL["G"], lw=1.4)
        _ground(ax, x_ground, y_bus-0.8, 0.7)
    else:
        # Semidirecta: la tension se toma directo de la linea (sin TP), en una derivacion
        # propia por conductor con punto de empalme. N a la izquierda, R a la derecha.
        lineas = (["N"] if show_N else []) + list(reversed(all_ph))
        v_tap = {c: 24.0 + 6.5*k for k, c in enumerate(lineas)}

    # ---------- BLOQUE DE PRUEBA ----------
    bx0,bx1=76,104
    by1 = 149 if respaldo else 98
    step=min(8.4,(by1-12)/max(n,1))
    by0=by1-(n*step)-4
    ax.add_patch(FancyBboxPatch((bx0,by0),bx1-bx0,by1-by0,boxstyle="round,pad=0.5,rounding_size=2.5",
                 fill=True,fc="#EEF2F6",ec="#2B2B2B",lw=2,zorder=1))
    blab="BLOQUE DE PRUEBA  "+("(13 term.)" if norma=="CENS" else "(B1-B26)")
    ax.text((bx0+bx1)/2,by1+1.4,blab,ha="center",va="bottom",fontsize=10.5,fontweight="bold",color=INK)
    ys=np.linspace(by1-step*0.7,by0+step*0.7,n)
    xL,xR=bx0+5,bx1-5; row={}
    for (tlbl,rot,kind,ph,io),y in zip(terms,ys):
        row[tlbl]=(y,ph,kind,rot,io); c=COL[ph]
        ax.add_patch(Circle((xL,y),0.95,fc="white",ec=c,lw=1.9,zorder=4))
        ax.add_patch(Circle((xR,y),0.95,fc="white",ec=c,lw=1.9,zorder=4))
        if kind=="I":
            ax.plot([xL+0.95,xR-0.95],[y,y],color="#2B2B2B",lw=3.4,zorder=3,solid_capstyle="round")
            ax.add_patch(Circle(((xL+xR)/2,y),0.5,fc="#2B2B2B",ec="#2B2B2B",zorder=4))
        else:
            ax.plot([xL+0.95,xR-0.95],[y,y],color="#9AA3AD",lw=1.6,zorder=3)
        ax.text((xL+xR)/2,y+1.7,tlbl,ha="center",va="bottom",fontsize=8,color=INK,fontweight="bold")
        ax.text((xL+xR)/2,y-1.9,rot,ha="center",va="top",fontsize=7.5,color=c,fontweight="bold")

    # Puente tri3h Aron: C1(3) -> C2(6) en el lado derecho de la bornera
    # y de ese punto sale cable al borne 4 del medidor
    if sistema == "tri3h":
        idx3 = next((i for i,(t,*_) in enumerate(terms) if t=="3"), None)
        idx6 = next((i for i,(t,*_) in enumerate(terms) if t=="6"), None)
        if idx3 is not None and idx6 is not None:
            y3 = ys[idx3]; y6 = ys[idx6]
            yp = (y3+y6)/2
            # puente vertical entre C1 y C2 en xR
            ax.plot([xR, xR],[y3, y6], color=INK, lw=2.2, zorder=5)
            ax.add_patch(Circle((xR, yp), 0.7, fc=INK, ec=INK, zorder=6))

    # ---------- MEDIDOR(ES) ----------
    # El medidor muestra sus bornes en ORDEN FISICO (1,2,3,4,5,6,7,8,9,11)
    # de arriba a abajo, independiente del orden del bloque.
    # El ruteo conecta: borne N del bloque -> borne N del medidor (mismo número).
    # Como el orden físico del medidor difiere del orden visual del bloque,
    # el cable hace una L: horizontal desde xR hasta una columna xm, luego
    # vertical hasta la Y del borne en el medidor, luego horizontal al medidor.

    # Orden físico del medidor según sistema
    if sistema == "tri4h":
        meter_order = ["1","2","3","4","5","6","7","8","9","11"]
    elif sistema == "tri3h":
        meter_order = ["1","2","3","4","5","6","7","8","9"]
    elif sistema == "bifasico":
        meter_order = ["1","2","3","4","5","6","7"]
    else:  # mono
        meter_order = ["1","2","3","4"]

    # Mapa tlbl -> (tipo, fase, color) para colorear bornes del medidor
    term_info = {t[0]: t for t in terms}

    def draw_meter(mx0, mx1, y_top, etq, ystep=None):
        """
        y_top: Y de la parte superior del área de bornes del medidor.
        ystep: paso vertical entre bornes (por defecto usa el paso del bloque).
        """
        ms = ystep if ystep is not None else step
        n_m = len(meter_order)
        # Y de cada borne del medidor en orden físico, de arriba a abajo
        ys_m = np.array([y_top - i*ms for i in range(n_m)])
        my0 = ys_m[-1] - ms*0.5
        my1 = y_top    + ms*0.5 + 14
        ax.add_patch(FancyBboxPatch((mx0,my0),mx1-mx0,my1-my0,
                     boxstyle="round,pad=0.6,rounding_size=3",
                     fill=True,fc=INK,ec="#0B0F14",lw=2,zorder=2))
        ax.text((mx0+mx1)/2, my1-4.5, etq, ha="center", va="center",
                fontsize=12, fontweight="bold", color="white")
        ax.add_patch(Rectangle((mx0+6,my1-17),(mx1-mx0)-12,7,
                     fc="#0B3D2E",ec="#0A5",lw=1))
        ax.text((mx0+mx1)/2,my1-13.5,"kWh   kvarh",ha="center",va="center",
                fontsize=8.5,color="#36df8f",family="monospace")
        mxr = mx0 + 2.4
        m_y = {}
        for tlbl, yy in zip(meter_order, ys_m):
            info = term_info.get(tlbl)
            c = COL[info[3]] if info else "#888"
            ax.add_patch(Circle((mxr,yy),0.85,fc="white",ec=c,lw=1.7,zorder=5))
            ax.text(mxr+1.6, yy, tlbl, ha="left", va="center",
                    fontsize=7, color="white", fontweight="bold")
            m_y[tlbl] = yy
        return m_y, mxr

    # Puente EN LA BORNERA del medidor (tri3h): bornes 3, 6 y 9
    # Se dibuja en draw_meter después de que m_y esté construido
    def draw_meter_bridges(m_y, mxr):
        for tlbl_src, destinos in meter_bridges(sistema):
            if tlbl_src not in m_y:
                continue
            ys_b = [m_y[tlbl_src]] + [m_y[d] for d in destinos if d in m_y]
            if len(ys_b) < 2:
                continue
            # puente en el lado IZQUIERDO de la bornera del medidor (mxr)
            # línea vertical conectando los bornes, sin salir hacia afuera
            xp = mxr - 2.0
            for yy in ys_b:
                ax.plot([mxr, xp],[yy, yy], color="white", lw=1.8, zorder=7)
            ax.plot([xp, xp],[min(ys_b), max(ys_b)], color="white", lw=1.8, zorder=7)

    # Posición vertical: el medidor empieza en la misma Y que el bloque (by1-step*0.7)
    meter_top = by1 - step*0.7
    mx_w = 32   # ancho de medidor
    if not respaldo:
        mx0 = 132; mx1 = mx0 + mx_w
        m_y0, mxr0 = draw_meter(mx0, mx1, meter_top, "MEDIDOR")
        draw_meter_bridges(m_y0, mxr0)
        meters = [(m_y0, mxr0)]
    else:
        # APILADO: PRINCIPAL arriba, RESPALDO abajo (misma columna x, distinto y)
        m_step  = step * 0.65   # paso reducido para que quepan los dos
        n_m     = len(meter_order)
        gap_m_v = 10            # espacio vertical entre cuerpos de medidor

        mx0_p = 124; mx1_p = mx0_p + mx_w   # columna del medidor
        y_top_p = meter_top    # PRINCIPAL: mismo nivel superior que el bloque

        m_yp, mxrp = draw_meter(mx0_p, mx1_p, y_top_p, "PRINCIPAL", ystep=m_step)

        # RESPALDO: justo debajo de PRINCIPAL
        my0_p   = y_top_p - (n_m - 1) * m_step - m_step * 0.5
        y_top_r = my0_p - gap_m_v - m_step * 0.5 - 14
        m_yr, mxrr = draw_meter(mx0_p, mx1_p, y_top_r, "RESPALDO", ystep=m_step)

        draw_meter_bridges(m_yp, mxrp)
        draw_meter_bridges(m_yr, mxrr)
        meters = [(m_yp, mxrp), (m_yr, mxrr)]

    # ---------- RUTEO ACOMETIDA -> BLOQUE ----------
    # Reglas confirmadas por el usuario:
    #   "in"      : corriente viene del BORNE DERECHO del TC (salida hacia carga)
    #               -> se conecta al borne DERECHO del bloque (xR)
    #   "cierre"  : viene del BORNE IZQUIERDO del TC (entrada de corriente)
    #               -> se conecta al borne IZQUIERDO del bloque (xL)
    #   tension V : viene del terminal 'a' del secundario del TP (semidirecta: de una
    #               derivacion de la linea)
    #   neutro N  : viene de la barra BN (comun de los secundarios de los TP)
    #   "puente"  : se puentea internamente en el medidor, NO recibe cable propio
    # Cada cable: terminal -> columna vertical PROPIA -> riel horizontal -> columna del
    # bloque -> fila del bloque. Los rieles van DEBAJO del neutro (antes algunos corrian a
    # 1 unidad de la linea de fase S y se leian como parte de ella).
    src={}     # tlbl -> (puntos previos, x de la columna vertical)
    for (tlbl,rot,kind,ph,io) in terms:
        if io == "puente":
            continue   # bornera puenteada internamente, sin cable al bloque
        if kind=="I" and io in ("in","cierre") and has_tc:
            src[tlbl]=(tc_pre[(ph,io)], tc_xs[(ph,io)])
        elif kind=="V" and has_tp and ph=="N":
            src[tlbl]=([(x_ntap, y_bus)], x_ntap)
        elif kind=="V" and has_tp and ph in tp_a:
            xa, ya = tp_a[ph]
            src[tlbl]=([(xa, ya)], xa)
        elif kind=="V" and not has_tp:
            linea = "S" if (ph=="N" and not show_N) else ph       # Aron: la referencia es la fase S
            xt = v_tap[linea]; yt = y_N if linea=="N" else y_ph[linea]
            ax.add_patch(Circle((xt, yt), 0.5, fc=COL[linea], ec=COL[linea], zorder=6))
            src[tlbl]=([(xt, yt)], xt)
    if sistema == "tri3h" and has_tc and ("T","cierre") in tc_pre:
        # S1 del TC-T al borne C2 del bloque: sin este cable el secundario del TC-T quedaba abierto
        src["6"]=(tc_pre[("T","cierre")], tc_xs[("T","cierre")])

    order=[t[0] for t in terms if t[4] not in ("puente","puente_3")]
    order_src=[t[0] for t in terms if t[4] not in ("puente","puente_3") or (t[0]=="6" and "6" in src)]
    lane_x=dict(zip(order_src,np.linspace(58,71,len(order_src))))
    rail_y=dict(zip(order_src,np.linspace(y_bus-3,by0+3,len(order_src))))
    for tlbl in order_src:
        if tlbl not in src:
            continue
        pre, xs = src[tlbl]
        lx=lane_x[tlbl]; ry=rail_y[tlbl]
        by=row[tlbl][0]; ph=row[tlbl][1]; c=COL[ph]
        io=row[tlbl][4]
        ls=(0,(6,3)) if ph=="N" else "-"
        w=2.3 if row[tlbl][2]=="I" else 1.7
        # Corriente "in" sale del borne DERECHO del bloque (xR); el resto, del IZQUIERDO (xL)
        bx = xR if io=="in" else xL
        pts = list(pre) + [(xs, pre[-1][1]), (xs, ry), (lx, ry), (lx, by), (bx, by)]
        ax.plot([q[0] for q in pts],[q[1] for q in pts],color=c,lw=w,ls=ls,solid_joinstyle="round")

    # ---------- BLOQUE -> MEDIDOR(ES) ----------
    # Cada borne N del bloque -> mismo borne N del medidor.
    # Como el orden visual difiere, se traza una L:
    #   xR (bloque) horizontal hasta columna xm,
    #   vertical hasta Y del borne en el medidor,
    #   horizontal hasta mxr (medidor).
    # Columnas xm separadas para no solaparse (una por borne del order)
    if not respaldo:
        # Sin respaldo: ruteo simple bloque->medidor
        xm_cols = np.linspace(106, 120, len(order))
        xm_map  = {tlbl: xm_cols[i] for i, tlbl in enumerate(order)}
        m_y, mxr = meters[0]
        for tlbl in order:
            if tlbl not in m_y or tlbl not in row:
                continue
            if sistema == "tri3h" and tlbl == "3":
                continue
            yb = row[tlbl][0]; ym = m_y[tlbl]
            ph = row[tlbl][1]; c = COL[ph]
            ls = (0,(6,3)) if ph=="N" else "-"
            xm = xm_map[tlbl]
            ax.plot([xR, xm],[yb, yb], color=c, lw=1.8, ls=ls)
            ax.plot([xm, xm],[yb, ym], color=c, lw=1.8, ls=ls)
            ax.plot([xm, mxr],[ym, ym], color=c, lw=1.8, ls=ls)
    else:
        # CON RESPALDO: corriente SERIE, tensión PARALELO (layout apilado vertical)
        # PRINCIPAL arriba, RESPALDO abajo — misma columna x, puente VERTICAL entre ellos
        m_yp, mxrp = meters[0]  # PRINCIPAL (arriba)
        m_yr, mxrr = meters[1]  # RESPALDO  (abajo)


        # Bornes de corriente por sistema
        if sistema == "tri4h":
            bornes_I_in  = {"1":"R","4":"S","7":"T"}
            bornes_I_out = {"3":"R","6":"S","9":"T"}
            bornes_V     = {"2":"R","5":"S","8":"T"}
            bornes_N     = {"11":"N"}
        elif sistema == "tri3h":
            bornes_I_in  = {"1":"R","7":"T"}
            bornes_I_out = {"3":"R","9":"T"}
            bornes_V     = {"2":"R","4":"S","8":"T"}
            bornes_N     = {}
        elif sistema == "bifasico":
            bornes_I_in  = {"1":"R","4":"S"}
            bornes_I_out = {"3":"R","6":"S"}
            bornes_V     = {"2":"R","5":"S"}
            bornes_N     = {"7":"N"}
        else:  # mono
            bornes_I_in  = {"1":"R"}
            bornes_I_out = {"3":"R"}
            bornes_V     = {"2":"R"}
            bornes_N     = {"4":"N"}

        # Columnas de ruteo entre bloque (xR) y medidores
        n_terms_total = len(order)
        xm_cols = np.linspace(106, 120, n_terms_total)
        xm_map  = {tlbl: xm_cols[i] for i, tlbl in enumerate(order)}

        # 1. CORRIENTE ENTRADA (bloque xR -> PRINCIPAL, bornes I_in)
        for tlbl, ph in bornes_I_in.items():
            if tlbl not in m_yp or tlbl not in row:
                continue
            yb = row[tlbl][0]; ym = m_yp[tlbl]
            c = COL[ph]; xm = xm_map.get(tlbl, 106)
            ax.plot([xR, xm],[yb, yb], color=c, lw=2.0)
            ax.plot([xm, xm],[yb, ym], color=c, lw=2.0)
            ax.plot([xm, mxrp],[ym, ym], color=c, lw=2.0)

        # 2. PUENTE SERIE VERTICAL (PRINCIPAL borne_out -> RESPALDO borne_in)
        # Los cables bajan por columnas justo a la izquierda del medidor (x < mx0_p)
        n_bridge = max(len(bornes_I_out), 1)
        xbr_cols = np.linspace(mx0_p - 3, mx0_p - 3*n_bridge, n_bridge)
        xbr_map  = dict(zip(bornes_I_out.keys(), xbr_cols))

        for (tlbl_out, ph), tlbl_in in zip(bornes_I_out.items(), bornes_I_in.keys()):
            c = COL[ph]
            if tlbl_out not in m_yp or tlbl_in not in m_yr:
                continue
            ym_out = m_yp[tlbl_out]   # PRINCIPAL borne salida
            ym_in  = m_yr[tlbl_in]    # RESPALDO  borne entrada
            xbr    = xbr_map[tlbl_out]
            # PRINCIPAL out → izquierda → baja → RESPALDO in
            ax.plot([mxrp, xbr],[ym_out, ym_out], color=c, lw=1.8)
            ax.plot([xbr,  xbr],[ym_out, ym_in],  color=c, lw=1.8)
            ax.plot([xbr, mxrr],[ym_in,  ym_in],  color=c, lw=1.8)
            ax.text(xbr - 1, (ym_out+ym_in)/2, f"{tlbl_out}→{tlbl_in}",
                    fontsize=5.5, color=c, va="center", ha="right", style="italic")
            ax.add_patch(Circle((xbr, ym_out), 0.55, fc=c, ec=c, zorder=6))
            ax.add_patch(Circle((xbr, ym_in),  0.55, fc=c, ec=c, zorder=6))

        # 3. CIERRE RETORNO (RESPALDO borne_out -> bloque cierre, línea punteada)
        # Ruta: RESPALDO out → izquierda → SUBE por encima del bloque (aguas arriba)
        #       → izquierda hasta columna junto al bloque → baja al borne cierre
        y_top_bus = by1 + 5   # bus horizontal por encima del bloque

        for ci, (tlbl_out, ph) in enumerate(bornes_I_out.items()):
            if tlbl_out not in m_yr or tlbl_out not in row:
                continue
            yb_cierre = row[tlbl_out][0]   # borne cierre en el bloque
            ym_rout   = m_yr[tlbl_out]     # RESPALDO borne salida y
            x_out     = mx0_p - 4 - ci*2  # columna lateral izquierda del medidor
            y_top     = y_top_bus + ci*2   # bus superior escalonado por fase (sube)
            xret      = xL - 3 - ci*2     # columna de retorno junto al bloque
            c = COL[ph]; ls = (0,(4,2))
            ax.plot([mxrr,  x_out],[ym_rout,  ym_rout],   color=c, lw=1.5, ls=ls)
            ax.plot([x_out, x_out],[ym_rout,  y_top],     color=c, lw=1.5, ls=ls)
            ax.plot([x_out, xret], [y_top,    y_top],     color=c, lw=1.5, ls=ls)
            ax.plot([xret,  xret], [y_top,    yb_cierre], color=c, lw=1.5, ls=ls)
            ax.plot([xret,  xL],   [yb_cierre,yb_cierre], color=c, lw=1.5, ls=ls)

        # 4. TENSIÓN PARALELO: bloque → T-junction en columna → PRINCIPAL (arriba)
        #    y desde la misma columna → RESPALDO (abajo)
        all_V = {**bornes_V, **bornes_N}
        n_V = max(len(all_V), 1)
        xv_cols = np.linspace(106, 120, n_V)

        for i_v, (tlbl, ph) in enumerate(all_V.items()):
            if tlbl not in row:
                continue
            c = COL[ph]; ls = (0,(6,3)) if ph=="N" else "-"
            yb = row[tlbl][0]; xv = xv_cols[i_v]
            ax.plot([xR, xv],[yb, yb], color=c, lw=1.6, ls=ls)

            ym_p = m_yp.get(tlbl)
            ym_r = m_yr.get(tlbl)

            if ym_p is not None:
                ax.plot([xv, xv],   [yb,  ym_p], color=c, lw=1.5, ls=ls)
                ax.plot([xv, mxrp], [ym_p, ym_p], color=c, lw=1.5, ls=ls)
            if ym_r is not None:
                ax.plot([xv, xv],   [yb,  ym_r], color=c, lw=1.3, ls=ls, zorder=1)
                ax.plot([xv, mxrr], [ym_r, ym_r], color=c, lw=1.3, ls=ls)
            if ym_p is not None and ym_r is not None:
                # T-junction visible en la columna de ruteo
                ax.add_patch(Circle((xv, yb), 0.65, fc=c, ec=c, zorder=6))

    # tri3h: puente C1->C2 en bornera (solo puntos en C1 y C2, no en el medio)
    # y cable desde C1 al borne 4 del medidor
    if sistema == "tri3h":
        idx3 = next((i for i,(t,*_) in enumerate(terms) if t=="3"), None)
        idx6 = next((i for i,(t,*_) in enumerate(terms) if t=="6"), None)
        if idx3 is not None and idx6 is not None:
            y3 = ys[idx3]; y6 = ys[idx6]
            xp = xR + 1.5  # justo afuera del borde derecho de la bornera
            # línea vertical entre C1 y C2 fuera del borde
            ax.plot([xp, xp],[y3, y6], color=INK, lw=2.2, zorder=5)
            # puntos solo en C1 y C2, no en el medio
            ax.plot([xR, xp],[y3, y3], color=INK, lw=2.2, zorder=5)
            ax.plot([xR, xp],[y6, y6], color=INK, lw=2.2, zorder=5)
            ax.add_patch(Circle((xp, y3), 0.7, fc=INK, ec=INK, zorder=6))
            ax.add_patch(Circle((xp, y6), 0.7, fc=INK, ec=INK, zorder=6))
            # cable desde C1 (xp, y3) al borne 4 del medidor
            for m_y, mxr in meters:
                if "4" in m_y:
                    ym4 = m_y["4"]
                    xm4 = 115
                    ax.plot([xp, xm4],[y3, y3], color=INK, lw=1.7)
                    ax.plot([xm4, xm4],[y3, ym4], color=INK, lw=1.7)
                    ax.plot([xm4, mxr],[ym4, ym4], color=INK, lw=1.7)

    # Aron con respaldo: cables externos especiales entre medidores
    if sistema == "tri3h" and respaldo and len(meters) == 2:
        m_y_princ, mxr_princ = meters[0]
        m_y_cheq,  mxr_cheq  = meters[1]
        x_extra = mxr_cheq + 8

        if "3" in row and "1" in m_y_cheq:
            yb3  = row["3"][0]
            y1ch = m_y_cheq["1"]
            ax.plot([xR, x_extra],[yb3, yb3], color=COL["R"], lw=1.7)
            ax.plot([x_extra, x_extra],[yb3, y1ch], color=COL["R"], lw=1.5)
            ax.plot([x_extra, mxr_cheq],[y1ch, y1ch], color=COL["R"], lw=1.5)
            ax.text(x_extra+0.5,(yb3+y1ch)/2,"B3→1",fontsize=6.5,color=COL["R"],
                    ha="left",va="center",style="italic")

        if "4" in m_y_cheq and "6" in m_y_princ:
            y4ch = m_y_cheq["4"]
            y6pr = m_y_princ["6"]
            xlink = x_extra + 4
            ax.plot([mxr_cheq, xlink],[y4ch, y4ch], color=COL["N"], lw=1.5, ls=(0,(4,2)))
            ax.plot([xlink, xlink],[y4ch, y6pr],    color=COL["N"], lw=1.5, ls=(0,(4,2)))
            ax.plot([xlink, mxr_princ],[y6pr, y6pr],color=COL["N"], lw=1.5, ls=(0,(4,2)))
            ax.text(xlink+0.5,(y4ch+y6pr)/2,"4→6",fontsize=6.5,color=COL["N"],
                    ha="left",va="center",style="italic")

    # ---------- SALIDA A CARGA (linea de potencia, solo fases de corriente) ----------
    # cx0: borde derecho del medidor mas a la derecha
    cx0 = 200 if respaldo else 164
    out_y = {}
    for i, ph in enumerate(cur_ph):
        yy = y_ph[ph]
        out_y[ph] = yy
        ax.plot([cx0, cx0+14], [yy, yy], color=COL[ph], lw=3, zorder=2)
    if show_N:
        ax.plot([cx0, cx0+14], [y_N, y_N], color=COL["N"], lw=2, ls=(0,(6,3)), zorder=2)

    # Seccionador (si aplica) en la salida hacia la carga
    sec_amp = cfg.get("interruptor") or (f"{cfg.get('tc_amp')} A" if cfg.get("tc_amp") else "")
    if cfg.get("seccionamiento") or cfg.get("interruptor"):
        scx = cx0+7
        ymin = min(out_y.values()) if out_y else y_N
        ymax = max(out_y.values()) if out_y else y_N
        for ph,yy in out_y.items():
            _u_disc(ax, scx, yy, INK, 0.55)
        ax.text(scx, ymax+5.5, f"Seccionador\n{sec_amp}", ha="center", va="bottom",
                fontsize=8, color=INK, fontweight="bold")

    for ph,yy in out_y.items():
        ax.text(cx0+15, yy, f"Fase {ph}", ha="left", va="center", fontsize=10,
                fontweight="bold", color=COL[ph])
    if show_N:
        ax.text(cx0+15, y_N, "Neutro", ha="left", va="center", fontsize=10,
                fontweight="bold", color=COL["N"])
    ax.text(cx0+7, max(y_ph.values())+4.5, "CARGA", ha="center", fontsize=9,
            color="#444", style="italic", fontweight="bold")

    # ---------- LEYENDA ----------
    leg=[Line2D([0],[0],color=COL["R"],lw=3,label="Fase R"),
         Line2D([0],[0],color=COL["S"],lw=3,label="Fase S"),
         Line2D([0],[0],color=COL["T"],lw=3,label="Fase T"),
         Line2D([0],[0],color=COL["N"],lw=2,ls=(0,(6,3)),label="Neutro"),
         Line2D([0],[0],color="#2B2B2B",lw=3.2,label="Cortocircuitador de corriente"),
         Line2D([0],[0],color="#9AA3AD",lw=1.6,label="Puente de tension (aislador)")]
    ax.legend(handles=leg,loc="lower left",bbox_to_anchor=(0.005,0.005),fontsize=8.5,
              framealpha=0.96,ncol=3,title="Convencion")

    plt.tight_layout(); plt.savefig(out_path,dpi=160,bbox_inches="tight",facecolor="white"); plt.close(fig)
    return out_path


# ============================================================
#  DIAGRAMA UNIFILAR - version generica con barraje/transformador
# ============================================================
# ============================================================
#  UNIFILAR MEDIDA INDIRECTA — estilo "plano limpio" (vertical)
#  Basado en el ejemplo del usuario (script de unifilar indirecta 13,2 kV):
#  RED -> TC -> derivacion TP -> [seccionador] -> trafo -> A CARGA, con el
#  medidor a la izquierda unido por los secundarios punteados (TC azul, TP
#  verde) y un cuadro de datos al pie. Sin cuadro de punto de conexion.
# ============================================================
_SIS_PRO = {   # sistema -> (adjetivo MAYUS, adjetivo, fases, n_elem, polos, texto medidor)
    "mono":     ("MONOFÁSICA", "monofásica", "1φ", 1, "unipolar", "Medidor monofásico\n1 elemento – 2 hilos"),
    "bifasico": ("BIFÁSICA",   "bifásica",   "2φ", 2, "bipolar",  "Medidor bifásico\n2 elementos – 3 hilos"),
    "tri3h":    ("TRIFÁSICA",  "trifásica",  "3φ", 2, "tripolar", "Medidor trifásico\n2 elementos – 3 hilos (Aron)"),
    "tri4h":    ("TRIFÁSICA",  "trifásica",  "3φ", 3, "tripolar", "Medidor trifásico\n3 elementos – 4 hilos"),
}

def _kv_de(v_mt):
    """Tension MT en kV (float) o None. '13.2 kV' / '13,2kV' -> 13.2; tambien '13200 V', '13.200 V', '13200' (->13.2)
    y '13.2' sin unidad. Una tension de BT ('220 V') NO es MT -> None."""
    s = str(v_mt or "").lower().strip()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:kv|kilovoltios?|kilovolts?)", s)
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.fullmatch(r"(\d{1,3}(?:[.,\s]\d{3})+|\d+(?:[.,]\d+)?)\s*(v|voltios?|volts?)?", s)
    if not m:
        return None
    txt, unidad = m.group(1), m.group(2)
    if re.fullmatch(r"\d{1,3}(?:[.,\s]\d{3})+", txt):
        v = float(re.sub(r"[.,\s]", "", txt))
    else:
        v = float(txt.replace(",", "."))
    if v >= 1000:
        return v / 1000.0
    return v if (unidad is None and 1.0 < v <= 69.0) else None      # sin unidad solo vale un valor de MT (13.2, 34.5...)

# Tensiones normalizadas MT/AT (kV) para deducir la red cuando solo se conoce el TP
_STD_KV = (4.16, 6.6, 11.4, 13.2, 13.8, 22.0, 33.0, 34.5, 44.0, 66.0, 110.0, 115.0, 230.0)

def _es(x, nd=1):
    """Numero con coma decimal (convencion del resto del plano: '13,2 kV')."""
    return f"{x:.{nd}f}".replace(".", ",")

def _num(v):
    m = re.search(r"\d+(?:[.,]\d+)?", str(v if v is not None else ""))
    return float(m.group().replace(",", ".")) if m else None

def _primario(rel):
    """'30/5' -> 30.0 ; '13200/120' -> 13200.0 ; None si no es una relacion."""
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*/\s*\d", str(rel or ""))
    return float(m.group(1).replace(",", ".")) if m else None

def _corriente_nominal(cfg):
    """(In [A], kV usado, estimada:bool) del trafo de un punto de medida
    indirecta con UN trafo, o (None, None, False) si faltan datos.
    kV sale de v_mt; si no hay, se deduce del primario del TP (L-L, o L-N si
    coincide con una tension normalizada / sqrt(3)) y se marca como estimada."""
    if "+" in str(cfg.get("trafo_kva", "")):
        return None, None, False
    kva = _num(cfg.get("trafo_kva"))
    if not kva:
        return None, None, False
    kv, estimada = _kv_de(cfg.get("v_mt")), False
    if kv is None:
        vp = _primario(cfg.get("rel_tp"))
        if not vp or vp < 1000:
            return None, None, False
        kv, estimada = vp / 1000.0, True
        if cfg.get("sistema", "tri4h") in ("tri3h", "tri4h"):
            for std in _STD_KV:                   # trifasico: primario fase-neutro (kV/sqrt3)?
                if abs(vp * math.sqrt(3) - std * 1000) <= 0.03 * std * 1000:
                    kv = std; break
        # mono/bifasico: la tension del TP ES la que alimenta el trafo -> sin conversion
    tri = cfg.get("sistema", "tri4h") in ("tri3h", "tri4h")
    return (kva / (math.sqrt(3) * kv) if tri else kva / kv), kv, estimada

def _validar_indirecta(cfg):
    """Chequeos numericos del punto de medida indirecta. Devuelve
    [(nivel, corto, largo)] con nivel 'ok'|'warn'|'err'; [] si no aplica o
    faltan datos. 'corto' va al cuadro de datos; 'largo' al aviso del bot.
    Criterios de DISENO (no una cita normativa): el TC debe llevar la corriente
    nominal del trafo dentro de ~20-100 % de su primario (maximo 120 %), y el
    primario del TP debe ser la tension de la red (L-L) o L-L/sqrt(3)."""
    out = []
    try:
        if cfg.get("tipo") != "indirecta":
            return out
        if int(cfg.get("n_trafos", 1) or 1) >= 2:
            return out
        rel_tc, rel_tp = str(cfg.get("rel_tc", "") or ""), str(cfg.get("rel_tp", "") or "")
        ip, vp = _primario(rel_tc), _primario(rel_tp)
        In, kv, est = _corriente_nominal(cfg)
        if In and ip:
            pct = In / ip * 100
            nota = " (kV estimado desde el TP)" if est else ""
            nota_c = " [kV est. del TP]" if est else ""
            if pct > 120:
                out.append(("err",
                    f"TC {rel_tc} subdimensionado: In = {_es(In)} A = {pct:.0f} % del primario (máx. 120 %){nota_c}",
                    f"El TC {rel_tc} queda subdimensionado: la corriente nominal del trafo ({_es(In)} A) es "
                    f"{pct:.0f} % de su primario (máximo recomendado 120 %){nota}. Usa un TC de mayor relación."))
            elif pct > 100:
                out.append(("warn",
                    f"TC {rel_tc} justo: In = {_es(In)} A = {pct:.0f} % del primario (sin margen){nota_c}",
                    f"El TC {rel_tc} queda justo: la corriente nominal del trafo ({_es(In)} A) es {pct:.0f} % de "
                    f"su primario, sin margen de sobrecarga{nota}. Considera la siguiente relación normalizada."))
            elif pct < 20:
                out.append(("warn",
                    f"TC {rel_tc} sobredimensionado: In = {_es(In)} A = {pct:.0f} % del primario{nota_c}",
                    f"El TC {rel_tc} queda sobredimensionado: la corriente nominal del trafo ({_es(In)} A) es solo "
                    f"{pct:.0f} % de su primario{nota}; la exactitud a baja carga puede degradarse."))
            else:
                out.append(("ok",
                    f"TC {rel_tc}: In = {_es(In)} A = {pct:.0f} % del primario{nota_c}",
                    f"TC {rel_tc}: In = {_es(In)} A = {pct:.0f} % del primario."))
        kv_red = _kv_de(cfg.get("v_mt"))
        if vp and kv_red:
            ll, ln = kv_red * 1000, kv_red * 1000 / math.sqrt(3)
            if abs(vp - ll) <= 0.03 * ll:
                out.append(("ok", f"TP {rel_tp}: primario = tensión de línea ({_es(kv_red)} kV)",
                                  f"TP {rel_tp}: primario = tensión de línea."))
            elif abs(vp - ln) <= 0.03 * ln:
                out.append(("ok", f"TP {rel_tp}: primario fase-neutro ({_es(kv_red)} kV/√3)",
                                  f"TP {rel_tp}: primario fase-neutro."))
            else:
                out.append(("warn",
                    f"TP {rel_tp}: su primario no coincide con la red de {_es(kv_red)} kV",
                    f"El primario del TP ({vp:.0f} V) no coincide con la red de {_es(kv_red)} kV "
                    f"(ni {ll:.0f} V línea-línea ni {ln:.0f} V fase-neutro)."))
    except (TypeError, ValueError, ZeroDivisionError):
        return []
    return out

# ============================================================
#  CAMPOS DE ACTA: varios transformadores, planta de respaldo, celda de medida
#  (todos opcionales; ver CLAUDE.md "Unifilar de frontera")
# ============================================================
_TRAFOS_MAX = 4          # maximo de transformadores dibujados; el resto se avisa ("+N no mostrados")
_VIOLETA = "#6A1B9A"     # borde de la celda de medida

def _t1(v, n=40):
    """Texto de usuario/PDF -> una linea recortada ('-', 'n.i', 'n/a' = no informado -> '')."""
    t = re.sub(r"\s+", " ", str(v if v is not None else "")).strip()[:n]
    return "" if t.lower().strip(".") in ("-", "--", "n.i", "ni", "n/i", "n.a", "na", "n/a", "null", "none") else t

def _tipo_txt(t):
    """'trifasico' -> 'trifásico' (solo para mostrar; el cfg conserva el valor original)."""
    return {"trifasico": "trifásico", "monofasico": "monofásico", "bifasico": "bifásico"}.get(str(t).lower(), t)

def _si_no(v):
    """True / False / None (no informado) desde bool o 'si'/'sí'/'no'."""
    if isinstance(v, bool): return v
    t = _t1(v, 10).lower().replace("í", "i")
    return True if t in ("si", "true", "1", "yes") else False if t in ("no", "false", "0") else None

def _kva_txt(k):
    return "" if k is None else (f"{k:g}".replace(".", ","))

def _trafos_de(cfg):
    """Lista normalizada de transformadores [{kva: float|None, tipo, uso}].
    `transformadores` (lista) manda; un `transformador` suelto es una lista de uno; si no
    hay ninguno, salen de los campos historicos trafo_* (solo si instalacion == 'trafo')."""
    crudo = cfg.get("transformadores")
    if not crudo and isinstance(cfg.get("transformador"), dict):
        crudo = [cfg["transformador"]]
    out = []
    if isinstance(crudo, (list, tuple)):
        for t in crudo:
            d = t if isinstance(t, dict) else ({"kva": t} if t not in (None, "") else None)
            if d is None: continue
            out.append({"kva": _num(d.get("kva")), "tipo": _t1(d.get("tipo"), 12).lower(),
                        "uso": _t1(d.get("uso"), 12).lower()})
    elif cfg.get("instalacion") == "trafo":
        lista = cfg.get("trafo_kva_list") or []
        base = {"tipo": _t1(cfg.get("trafo_tipo"), 12).lower(), "uso": _t1(cfg.get("trafo_uso"), 12).lower()}
        for k in (lista if lista else [cfg.get("trafo_kva")]):
            out.append(dict(base, kva=_num(k)))
    return out

def _planta_de(cfg):
    """{existe, kva, transf} o None si el cfg no habla de planta de respaldo / dice que no hay."""
    p = cfg.get("planta_respaldo")
    if not isinstance(p, dict) or _si_no(p.get("existe")) is not True:
        return None
    tr = _t1(p.get("transferencia"), 12).lower().replace("á", "a")
    tr = tr if tr in ("automatica", "manual") else None
    return {"existe": True, "kva": _num(p.get("kva")), "transf": tr,
            "transf_txt": {"automatica": "automática", "manual": "manual"}.get(tr)}

def _celda_de(cfg):
    """None si no se informo; si no {existe: bool|None, tipo, estado}."""
    c = cfg.get("celda_medida")
    if not isinstance(c, dict): return None
    return {"existe": _si_no(c.get("existe")), "tipo": _t1(c.get("tipo"), 30), "estado": _t1(c.get("estado"), 30)}

def _ubic_medida(cfg):
    """'MT' | 'BT': lo declarado; por defecto MT si la medida es indirecta, BT en los demas casos."""
    u = _t1(cfg.get("ubicacion_medida"), 4).upper()
    return u if u in ("MT", "BT") else ("MT" if cfg.get("tipo") == "indirecta" else "BT")

def _clasif_creg(kva_total):
    """(tipo 1-5, MVA) segun CREG 038/2014 Tabla 1 (misma tabla que /clasificar)."""
    mva = kva_total / 1000.0
    return (1 if mva >= 30 else 2 if mva >= 1 else 3 if mva >= 0.1 else 4 if mva >= 0.01 else 5), mva

def _resumen_trafos(trafos):
    """'2 × 300 kVA' si son iguales; si no, 'TRF1 300 + TRF2 150 kVA'."""
    ks = [t["kva"] for t in trafos]
    if ks and None not in ks and len(set(ks)) == 1:
        return f"{len(ks)} × {_kva_txt(ks[0])} kVA"
    return " + ".join(f"TRF{i+1} {_kva_txt(t['kva']) or 'kVA n.i.'}" for i, t in enumerate(trafos)) \
           + (" kVA" if any(t["kva"] is not None for t in trafos) else "")

def _planta_simbolo(ax, x, y, planta, s=1.0, lado=-1, fs=1.0, med="MED1"):
    """Planta de respaldo: del nodo (x, y) de la barra de carga, hacia `lado` (-1 izq., +1 der.):
    ATS (caja) y generador (circulo con G). `s` = unidades por pulgada del renderer (1 en los
    verticales; ~9.7 en el generico) y `fs` el factor de tamano de fuente. Devuelve la x del borde
    exterior del dibujo y la y inferior de su rotulo (para acotar el lienzo)."""
    manual = planta["transf"] == "manual"
    w_ats = (1.5 if manual else 0.8) * s
    x_ats = x + lado * (0.3 * s + w_ats / 2)
    x_g = x + lado * (0.3 * s + w_ats + 1.1 * s)
    r = 0.5 * s
    # el cable va en TRAMOS (nodo -> ATS -> generador): atravesando los simbolos "por detras" se
    # veia bien pero era un trazo que cruzaba su rotulo
    ax.plot([x, x_ats - lado * w_ats / 2], [y, y], color="k", lw=2, zorder=2)
    ax.plot([x_ats + lado * w_ats / 2, x_g - lado * 0.5 * s], [y, y], color="k", lw=2, zorder=2)
    ax.add_patch(Rectangle((x_ats - w_ats / 2, y - 0.3 * s), w_ats, 0.6 * s, fc="white", ec="k", lw=2, zorder=4))
    ax.text(x_ats, y, "TRANSFERENCIA\nMANUAL" if manual else "ATS", ha="center", va="center",
            fontsize=(6.5 if manual else 9) * fs, fontweight="bold", zorder=6)
    ax.add_patch(Circle((x_g, y), r, fc="white", ec="k", lw=2, zorder=4))
    ax.text(x_g, y, "G", ha="center", va="center", fontsize=12 * fs, fontweight="bold", zorder=6)
    ax.add_patch(Circle((x, y), 0.07 * s, color="k", zorder=5))
    kva_p = "kVA no informado" if planta["kva"] is None else f"{_kva_txt(planta['kva'])} kVA"
    ax.text(x_g, y - r - 0.15 * s, f"Planta de respaldo\n(no medida por {med})\n{kva_p}",
            ha="center", va="top", fontsize=8.5 * fs, fontweight="bold")
    return x_g - 1.0 * s, y - r - 0.15 * s - 0.75 * s


def draw_unifilar_indirecta_pro(cfg, out_path):
    """Unifilar de medida INDIRECTA en vertical, estilo del ejemplo del usuario
    (v2). Un solo trafo (o sin trafo). Las subestaciones multi-celda (n_trafos>=2)
    y el estilo 'detallado' siguen en draw_unifilar_generico.

    v2 corrige tres debilidades de la v1:
      1. Circuito completo y "energizable": seccionador dibujado CERRADO
         (cfg['seccionador_estado']='abierto' lo abre), neutro del trafo a
         tierra + Dyn11, CC fusibles y pararrayos en la entrada MT.
      2. Simbolos distinguibles y secundarios correctos: TC = anillo sobre el
         conductor (rojo), TP = par de circulos (azul), trafo = par grande
         (negro); los secundarios pasan por el BLOQUE DE PRUEBAS (obligatorio
         en indirecta) con tierra, y cada color sigue a su transformador.
      3. Numeros validados: In del trafo vs primario del TC y primario del TP
         vs red (ver _validar_indirecta), en el cuadro de datos y en el aviso.
    """
    sistema = cfg.get("sistema", "tri4h")
    if sistema not in _SIS_PRO: sistema = "tri4h"
    SIS_MAY, sis_adj, fases, n_elem, polos, med_txt = _SIS_PRO[sistema]
    tri       = sistema in ("tri3h", "tri4h")
    norma     = cfg.get("norma", "RA8")
    rel_tc    = str(cfg.get("rel_tc", "") or "")
    rel_tp    = str(cfg.get("rel_tp", "") or "")
    respaldo  = bool(cfg.get("respaldo", False))
    instal    = cfg.get("instalacion") or ""
    kva       = re.sub(r"\s*kva\s*$", "", str(cfg.get("trafo_kva", "") or ""), flags=re.I).strip()
    secc_pos  = cfg.get("seccionador", "")
    secc_open = cfg.get("seccionador_estado") == "abierto"
    calibre   = cfg.get("calibre_conductor", "") or cfg.get("calibre_acometida", "")
    circuito  = str(cfg.get("circuito", "") or "").strip()
    subterr   = cfg.get("tendido") == "subterraneo"
    kv        = _kv_de(cfg.get("v_mt"))
    kv_es     = (f"{kv:g}".replace(".", ",") + " kV") if kv else ""
    volts_pto = f"{int(round(kv * 1000)):,}".replace(",", ".") + " V" if kv else ""   # 13.200 V
    volts_raw = f"{int(round(kv * 1000))} V" if kv else "M.T."                         # 13200 V
    def _n(v, d):
        try: return max(1, int(v))
        except (TypeError, ValueError): return d
    n_tc, n_tp = _n(cfg.get("n_tc"), n_elem), _n(cfg.get("n_tp"), n_elem)
    n_cc, dps_n = _n(cfg.get("n_cc"), n_elem), _n(cfg.get("dps_cantidad"), 1)
    In, _kv_in, _est = _corriente_nominal(cfg)
    validacion = _validar_indirecta(cfg)

    celda, planta, ub = _celda_de(cfg), _planta_de(cfg), _ubic_medida(cfg)
    celda_dib = bool(celda and celda["existe"] is True)           # recuadro violeta alrededor de TC + TP
    prot = cfg.get("proteccion_despues") or cfg.get("interruptor") or ""
    prot_det = "  ".join(p for p in (prot, f"{cfg.get('interruptor_polos')}P" if cfg.get("interruptor_polos") else None,
                                     cfg.get("interruptor_tipo")) if p) if prot else ""
    def _sec(rel, u):
        parte = rel.split("/")[-1].strip() if "/" in rel else ""
        return f"{parte} {u}" if re.fullmatch(r"\d+(?:[.,]\d+)?", parte) else ""
    sec_tc, sec_tp = _sec(rel_tc, "A"), _sec(rel_tp, "V")

    # ── Cuadro de datos (se arma antes: su altura decide el alto del lienzo) ──
    n_el_txt = f"{n_elem} elemento" + ("s" if n_elem != 1 else "")
    cab = f"Medida indirecta {sis_adj} – {n_el_txt}" + (" (Aron)" if sistema == "tri3h" else "") \
          + (" · Principal + Respaldo" if respaldo else "")
    l2 = []
    if instal == "trafo":
        l2.append(f"Transformador: {kva} kVA" + (f" ({_es(In)} A)" if In else "") if kva else "Transformador")
    if rel_tc: l2.append(f"TC: {rel_tc} A")
    if rel_tp: l2.append(f"TP: {rel_tp} V")
    l3 = []
    if kv_es: l3.append(f"Red: {kv_es}")
    if circuito: l3.append(f"Circuito: {circuito}")
    if secc_pos == "antes":
        l3.append(("Seccionador instalado después de la medida (antes del trafo, lado MT)")
                  + (" – ABIERTO" if secc_open else " – cerrado"))
    elif secc_pos == "despues":
        l3.append("Seccionador instalado después del trafo (lado BT)" + (" – ABIERTO" if secc_open else " – cerrado"))
    if prot_det: l3.append(f"Protección: {prot_det}")
    if calibre: l3.append(f"Calibre: {calibre}")
    if subterr: l3.append("Acometida subterránea")
    if ub == "BT" and instal == "trafo": l3.append("Punto de medición: lado BT del transformador")
    if celda_dib:
        l3.append("Celda de medida" + (": " + " · ".join(p for p in (celda["tipo"], celda["estado"]) if p)
                                       if (celda["tipo"] or celda["estado"]) else ""))
    elif celda and celda["existe"] is False and ub == "MT":
        l3.append("Sin celda de medida")
    if planta:
        l3.append("Planta de respaldo: Sí" + (f" ({_kva_txt(planta['kva'])} kVA)" if planta["kva"] is not None else "")
                  + (f" · transferencia {planta['transf_txt']}" if planta["transf"] else ""))
    SEP = "   |   "
    filas = [("b", cab)]
    if l2: filas.append(("n", SEP.join(l2)))
    linea = ""
    for item in l3:
        if linea and len(linea) + len(SEP) + len(item) > 105:
            filas.append(("n", linea)); linea = item
        else:
            linea = (linea + SEP + item) if linea else item
    if linea: filas.append(("n", linea))
    for nivel, corto, _largo in validacion:
        filas.append((nivel, {"ok": "✓ ", "warn": "⚠ ", "err": "✗ "}[nivel] + corto))
    filas.append(("i", f"Referencia: CREG 038/2014 · RETIE 2024 · Bornera {norma}"))
    cuadro_h = 0.3 + 0.4 * len(filas)

    # ── Alturas (offsets respecto a la barra de la red; negativos = hacia abajo)
    O_FUS, O_DPS = -1.0, -0.5
    # Con celda de medida dibujada: el recuadro violeta encierra TC + TP (baja 0,6 para no tocar el
    # pararrayos) y el seccionador/trafo bajan lo que mide el TP completo (esta DESPUES de la celda).
    d_top, d_cel = (0.6, 2.4) if celda_dib else (0.0, 0.0)
    O_TC = -2.4 - d_top
    O_TPN = O_TC - 1.2                  # nodo de derivacion del TP
    O_TPM = O_TPN - 0.8                 # centro del TP (= O_TC - 2.0)
    O_SECT, O_SECB = O_TPN - 1.3 - d_cel, O_TPN - 2.2 - d_cel
    O_TR1, O_TR2 = O_TPN - 4.2 - d_cel, O_TPN - 4.8 - d_cel
    trafo_top, trafo_bot = O_TR1 + 0.6, O_TPN - 5.4 - d_cel
    cursor = trafo_bot
    prot_c = secc_d_c = None
    if prot_det:
        prot_c = cursor; cursor -= 1.9
    if secc_pos == "despues":
        secc_d_c = cursor; cursor -= 1.9
    arrow_start = cursor
    cuadro_top = cursor - 1.8 - (0.5 if planta else 0)
    H = 1.6 + (-(cuadro_top - cuadro_h)) + 0.3
    W = 11.0
    bar = H - 1.6
    Y = lambda off: bar + off

    VERDE, ROJO, AZUL = COL["G"], COL["R"], COL["S"]
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off"); ax.set_aspect("equal")
    X = 5.5

    def L(x1, y1, x2, y2, lw=2, c="k", ls="-", z=2):
        ax.plot([x1, x2], [y1, y2], color=c, lw=lw, ls=ls, solid_capstyle="butt", zorder=z)
    def dot(x, y, r=0.07, c="k"):
        ax.add_patch(Circle((x, y), r, color=c, zorder=5))
    def tierra(x, y, c="k", k=1.0):
        L(x, y, x, y - 0.2 * k, c=c)
        for i, w in enumerate([0.4, 0.26, 0.12]):
            L(x - w * k, y - 0.2 * k - 0.12 * k * i, x + w * k, y - 0.2 * k - 0.12 * k * i, c=c)

    # Título y red
    titulo = f"DIAGRAMA UNIFILAR – MEDIDA INDIRECTA {SIS_MAY}" + (f" {kv_es}" if kv_es else "")
    ax.text(W / 2, H - 0.4, titulo, ha="center", fontsize=15, fontweight="bold")
    L(3.5, bar, 7.5, bar, lw=5)
    red_txt = "RED DE DISTRIBUCIÓN" + (f" {volts_pto}" if volts_pto else " M.T.") + f" – {fases}"
    ax.text(W / 2, bar + 0.35, red_txt, ha="center", fontsize=11, fontweight="bold")

    # ── Conductor principal (continuo; los simbolos se superponen) ────────────
    sub_ls = (0, (1.5, 1.2)) if subterr else "-"
    if secc_pos == "antes" and secc_open:
        L(X, bar, X, Y(O_SECT), ls=sub_ls)       # se corta en el seccionador abierto
        L(X, Y(O_SECB), X, Y(trafo_top if instal == "trafo" else arrow_start))
    else:
        L(X, bar, X, Y(trafo_top if instal == "trafo" else arrow_start), ls=sub_ls)

    # Entrada MT: pararrayos (derivacion a la derecha) y CC fusibles
    L(X, Y(O_DPS), X + 1.4, Y(O_DPS), c=VERDE, lw=1.6)
    ax.add_patch(Rectangle((X + 1.26, Y(O_DPS - 0.9)), 0.28, 0.6, fc="white", ec=VERDE, lw=2, zorder=4))
    ax.annotate("", xy=(X + 1.4, Y(O_DPS - 0.78)), xytext=(X + 1.4, Y(O_DPS - 0.42)),
                arrowprops=dict(arrowstyle="-|>", lw=1.6, color=VERDE))
    L(X + 1.4, Y(O_DPS), X + 1.4, Y(O_DPS - 0.3), c=VERDE, lw=1.6)
    tierra(X + 1.4, Y(O_DPS - 0.9), c=VERDE, k=0.8)
    ax.text(X + 1.75, Y(O_DPS - 0.6), "Pararrayos ZnO" + (f"\n(banco de {dps_n})" if dps_n > 1 else ""),
            ha="left", va="center", fontsize=10, fontweight="bold", color=VERDE)
    ax.add_patch(Rectangle((X - 0.13, Y(O_FUS - 0.28)), 0.26, 0.56, fc="white", ec="k", lw=2, zorder=4))
    L(X, Y(O_FUS + 0.28), X, Y(O_FUS - 0.28), z=5)
    ax.text(X - 0.35, Y(O_FUS), f"{n_cc} CC fusibles MT", ha="right", va="center", fontsize=10, fontweight="bold")

    # ── TC: anillo ROJO sobre el conductor (serie) ───────────────────────────
    ax.add_patch(Circle((X, Y(O_TC)), 0.32, fill=False, ec=ROJO, lw=2.6, zorder=6))
    ax.text(X + 0.55, Y(O_TC), f"{n_tc} × TC  {rel_tc + ' A' if rel_tc else '---'}",
            ha="left", va="center", fontsize=11, fontweight="bold", color=ROJO)

    # ── Derivación del TP: par de círculos AZUL, a tierra ────────────────────
    dot(X, Y(O_TPN))
    L(X, Y(O_TPN), 9.2, Y(O_TPN)); L(9.2, Y(O_TPN), 9.2, Y(O_TPN - 0.25))
    for dy in (0.55, 1.05):
        ax.add_patch(Circle((9.2, Y(O_TPN - dy)), 0.3, fc="white", ec=AZUL, lw=2.4, zorder=4))
    L(9.2, Y(O_TPN - 1.35), 9.2, Y(O_TPN - 1.9)); tierra(9.2, Y(O_TPN - 1.9), c=VERDE)
    ax.text(9.2, Y(O_TPN - 2.75), f"{n_tp} × TP\n{rel_tp + ' V' if rel_tp else '---'}",
            ha="center", va="center", fontsize=11, fontweight="bold", color=AZUL)

    if celda_dib:
        x1c = 10.5
        ax.add_patch(Rectangle((X - 0.5, Y(O_TPN - 3.4)), x1c - (X - 0.5), (O_TC + 0.7) - (O_TPN - 3.4),
                               fill=False, ec=_VIOLETA, lw=2.2, ls=(0, (6, 3)), zorder=1))
        ax.text(x1c, Y(O_TC + 0.7) + 0.08, "CELDA DE MEDIDA" + (f" – {celda['tipo']}" if celda["tipo"] else ""),
                ha="right", va="bottom", fontsize=9.5, fontweight="bold", color=_VIOLETA)
    elif celda and celda["existe"] is False and ub == "MT":
        ax.text(9.2, Y(O_TPN - 3.5), "Sin celda de medida", ha="center", va="center", fontsize=9,
                color="#555", style="italic")

    # ── Seccionador ANTES del trafo (lado MT): CERRADO por defecto ───────────
    def seccionador(yt, yb, etiqueta, abierto):
        dot(X, Y(yt)); dot(X, Y(yb))
        if abierto:
            L(X, Y(yt), X + 0.55, Y(yt - 0.75), lw=2.5)
        else:
            L(X, Y(yt), X, Y(yb), lw=2.5, z=3)                  # cuchilla cerrada sobre el contacto
            L(X, Y(yt), X + 0.3, Y(yt - 0.45), lw=2.5, c="k", z=3)   # manija
        ax.text(X + 0.6, Y((yt + yb) / 2 + 0.1), etiqueta, ha="left", va="center", fontsize=10, fontweight="bold")
    estado = "ABIERTO" if secc_open else "cerrado"
    if secc_pos == "antes":
        seccionador(O_SECT, O_SECB, f"Seccionador {polos}\n" + (kv_es if kv_es else "(lado MT)") + f"\n({estado})", secc_open)

    # ── Transformador: par grande NEGRO, neutro a tierra, Dyn11 ──────────────
    if instal == "trafo":
        for yy in (O_TR1, O_TR2):
            ax.add_patch(Circle((X, Y(yy)), 0.6, fc="white", ec="k", lw=2, zorder=4))
        L(X - 0.6, Y(O_TR2), X - 1.15, Y(O_TR2), c=VERDE, lw=1.6)      # neutro del secundario a tierra
        tierra(X - 1.15, Y(O_TR2), c=VERDE)
        tl = "Transformador" + (f"\n{kva} kVA" + (" · Dyn11" if tri else "") if kva else (" Dyn11" if tri else "")) \
             + f"\n{volts_raw} / BT" + (f"\nIn = {_es(In)} A" if In else "")
        ax.text(X + 0.9, Y((O_TR1 + O_TR2) / 2), tl, ha="left", va="center", fontsize=11, fontweight="bold")
    L(X, Y(trafo_bot if instal == "trafo" else trafo_top), X, Y(arrow_start))

    # Protección y seccionador BT (después del trafo)
    if prot_c is not None:
        yb = Y(prot_c - 0.95)
        ax.add_patch(Rectangle((X - 0.25, yb - 0.25), 0.5, 0.5, fc="white", ec="k", lw=2, zorder=4))
        ax.text(X + 0.55, yb, "Protección\n" + prot_det, ha="left", va="center", fontsize=10, fontweight="bold")
    if secc_d_c is not None:
        seccionador(secc_d_c - 0.45, secc_d_c - 1.35, f"Seccionador {polos}\n(lado BT)\n({estado})", secc_open)
    if calibre:
        ax.text(X - 0.25, Y(arrow_start - 0.35), calibre, ha="right", va="center", fontsize=9.5, color="#444", style="italic")
    ax.annotate("", xy=(X, Y(arrow_start - 1.05)), xytext=(X, Y(arrow_start - 0.7)),
                arrowprops=dict(arrowstyle="-|>", lw=2, color="k"))
    L(X, Y(arrow_start), X, Y(arrow_start - 0.7))
    ax.text(X, Y(arrow_start - 1.35), "A CARGA (BT)" if instal == "trafo" else "A CARGA", ha="center", fontsize=10.5)
    if planta:
        _planta_simbolo(ax, X, Y(arrow_start - 0.3), planta, 1.0, +1, 1.0)

    # ── Medidor(es) + BLOQUE DE PRUEBAS en los secundarios ───────────────────
    y_tc, y_tp = Y(O_TC), Y(O_TPM)
    y_m = (y_tc + y_tp) / 2
    bx0, bx1 = 3.15, 4.2
    rm = 0.75 if not respaldo else 0.6
    mxs = [1.55] if not respaldo else [0.95, 2.3]
    for k, mx in enumerate(mxs):
        ax.add_patch(Circle((mx, y_m), rm, fc="white", ec="k", lw=2, zorder=4))
        if respaldo:
            ax.text(mx, y_m + 0.3, "PRINCIPAL" if k == 0 else "RESPALDO", ha="center", va="center",
                    fontsize=6, fontweight="bold", zorder=6)
            ax.text(mx, y_m - 0.1, "kWh\nkVArh", ha="center", va="center", fontsize=8.5, fontweight="bold", zorder=6)
        elif planta:
            ax.text(mx, y_m + 0.3, "MED1", ha="center", va="center", fontsize=8, fontweight="bold", zorder=6)
            ax.text(mx, y_m - 0.15, "kWh\nkVArh", ha="center", va="center", fontsize=9.5, fontweight="bold", zorder=6)
        else:
            ax.text(mx, y_m, "kWh\nkVArh", ha="center", va="center", fontsize=11, fontweight="bold", zorder=6)
    ax.text(sum(mxs) / len(mxs), y_tp - 0.75, med_txt + "\n(medida indirecta)",
            ha="center", va="top", fontsize=10, fontweight="bold")
    # bloque de pruebas: caja vertical atravesada por ambos secundarios
    ax.add_patch(Rectangle((bx0, y_tp - 0.55), bx1 - bx0, (y_tc - y_tp) + 1.1, fc="white", ec="k", lw=2, zorder=3))
    ax.text((bx0 + bx1) / 2, y_m, "BLOQUE DE PRUEBAS", rotation=90, ha="center", va="center",
            fontsize=9, fontweight="bold", zorder=6)
    L((bx0 + bx1) / 2, y_tp - 0.55, (bx0 + bx1) / 2, y_tp - 0.75, c=VERDE, lw=1.4)       # secundarios a tierra
    tierra((bx0 + bx1) / 2, y_tp - 0.75, c=VERDE, k=0.7)
    if celda_dib:       # a la derecha del simbolo el rotulo cruzaba el borde del recuadro de la celda
        ax.text((bx0 + bx1) / 2, y_tp - 1.2, "secundarios\na tierra", ha="center", va="top",
                fontsize=8, color=VERDE, fontweight="bold")
    else:
        ax.text((bx0 + bx1) / 2 + 0.45, y_tp - 1.05, "secundarios\na tierra", ha="left", va="center",
                fontsize=8, color=VERDE, fontweight="bold")
    if sec_tc:
        L(X - 0.32, y_tc, bx1, y_tc, lw=1.7, c=ROJO, ls="--")
        L(bx0, y_tc, mxs[0], y_tc, lw=1.7, c=ROJO, ls="--")
        # dos lineas y centrado en el tramo bloque->TC (~1 u): en una linea llegaba al anillo
        ax.text((bx1 + 0.4) if celda_dib else (bx1 + X - 0.32) / 2, y_tc + 0.12, f"Sec. TC\n{sec_tc}",
                ha="center", va="bottom", fontsize=9.5, color=ROJO, fontweight="bold")
    if sec_tp:
        L(8.9, y_tp, bx1, y_tp, lw=1.7, c=AZUL, ls="--")
        L(bx0, y_tp, mxs[0], y_tp, lw=1.7, c=AZUL, ls="--")
        ax.text(7.2, y_tp + 0.12, f"Sec. TP – {sec_tp}", ha="center", fontsize=9.5, color=AZUL, fontweight="bold")
    for mx in mxs:
        if sec_tc: L(mx, y_tc, mx, y_m + rm, lw=1.7, c=ROJO, ls="--")
        if sec_tp: L(mx, y_tp, mx, y_m - rm, lw=1.7, c=AZUL, ls="--")
    if respaldo:
        for yy, c in ((y_tc, ROJO), (y_tp, AZUL)):
            dot(mxs[1], yy, r=0.06, c=c)

    # ── Cuadro de datos ──────────────────────────────────────────────────────
    ct = Y(cuadro_top)
    ax.add_patch(Rectangle((0.4, ct - cuadro_h), 10.2, cuadro_h, fc="white", ec="k", lw=2))
    col = {"ok": "#2E7D32", "warn": "#B26A00", "err": "#C62828"}
    yy = ct - 0.3
    for kind, txt in filas:
        ax.text(0.7, yy, txt, fontsize=9 if kind == "i" else 10, va="center",
                fontweight="bold" if kind in ("b", "err") else "normal",
                style="italic" if kind == "i" else "normal", color=col.get(kind, "black"))
        yy -= 0.4

    plt.savefig(out_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path

# ============================================================
#  UNIFILAR DE FRONTERA -- 2 o mas transformadores (paralelo / independientes)
# ============================================================
def draw_unifilar_frontera(cfg, out_path):
    """Unifilar vertical (mismo estilo "plano limpio" que draw_unifilar_indirecta_pro) para
    2-4 transformadores: cada TRFi en su columna, con su fusible FUi desde el barraje MT.
      - "paralelo" (por defecto): los secundarios confluyen en UN barraje BT comun y de ahi
        sigue un solo ramal (TC si lo hay -> BKR1 -> carga).
      - "independientes": cada TRFi alimenta su propio barraje BT, BKR y carga; MED1 mide solo el
        ramal de ESTA frontera (el primero que no es compartido) y los demas van punteados en gris.
    Celda de medida (MT), planta de respaldo con ATS y nota de punto de medicion como en el
    resto de los renderers. Se usa cuando cfg['transformadores'] trae 2 o mas elementos."""
    sistema = cfg.get("sistema", "tri4h")
    if sistema not in _SIS_PRO: sistema = "tri4h"
    SIS_MAY, sis_adj, fases, n_elem, polos, med_txt = _SIS_PRO[sistema]
    tipo = cfg.get("tipo", "indirecta")
    if tipo not in ("directa", "semidirecta", "indirecta"): tipo = "indirecta"
    tri = sistema in ("tri3h", "tri4h")
    norma = cfg.get("norma", "RA8")
    rel_tc = str(cfg.get("rel_tc", "") or ""); rel_tp = str(cfg.get("rel_tp", "") or "")
    respaldo = bool(cfg.get("respaldo", False))
    kv = _kv_de(cfg.get("v_mt"))
    kv_es = (f"{kv:g}".replace(".", ",") + " kV") if kv else ""
    volts_pto = f"{int(round(kv * 1000)):,}".replace(",", ".") + " V" if kv else ""
    circuito = str(cfg.get("circuito", "") or "").strip()
    calibre = cfg.get("calibre_conductor", "") or cfg.get("calibre_acometida", "")
    secc_pos, secc_open = cfg.get("seccionador", ""), cfg.get("seccionador_estado") == "abierto"
    prot = cfg.get("proteccion_despues") or cfg.get("interruptor") or cfg.get("proteccion_antes") or ""
    def _n(v, d):
        try: return max(1, int(v))
        except (TypeError, ValueError): return d
    n_tc, n_tp = _n(cfg.get("n_tc"), n_elem), _n(cfg.get("n_tp"), n_elem)
    dps_n = _n(cfg.get("dps_cantidad"), 1)

    trafos_all = _trafos_de(cfg)
    trafos = [dict(t, k=i + 1) for i, t in enumerate(trafos_all[:_TRAFOS_MAX])]
    n_tot = len(trafos_all)
    n = len(trafos)
    extra = n_tot - n
    conf = "independientes" if cfg.get("configuracion_transformadores") == "independientes" else "paralelo"
    ub = _ubic_medida(cfg)
    planta, celda = _planta_de(cfg), _celda_de(cfg)
    medida_mt = ub == "MT" and tipo in ("semidirecta", "indirecta")
    medida_bt_tc = ub == "BT" and tipo in ("semidirecta", "indirecta")
    medida_bt_directa = ub == "BT" and tipo == "directa"
    con_tp_mt = tipo == "indirecta"
    # ramal medido (independientes + medida en BT): el primero que no sea compartido; se dibuja
    # PRIMERO (a la izquierda: ahi van MED1 y la planta) conservando su numero TRFk.
    m_idx = 0
    if conf == "independientes" and not medida_mt:
        m_idx = next((i for i, t in enumerate(trafos) if t["uso"] != "compartido"), 0)
        trafos = [trafos[m_idx]] + [t for i, t in enumerate(trafos) if i != m_idx]

    VERDE, ROJO, AZUL, GRIS = COL["G"], COL["R"], COL["S"], "#9AA3AD"
    S = 3.5
    if conf == "paralelo":
        XC = max(5.8 if respaldo else 5.5, 2.8 + (n - 1) * S / 2)
        cols = [XC + (i - (n - 1) / 2) * S for i in range(n)]
    else:
        cols = [(5.8 if respaldo else 5.5) + i * S for i in range(n)]
        XC = sum(cols) / n
    W = max(11.0, cols[-1] + (4.6 if extra > 0 else 3.2), (XC + 5.7) if medida_mt and con_tp_mt else 0)

    fig, ax = plt.subplots(figsize=(W, 14))
    ax.axis("off"); ax.set_aspect("equal")

    def L(x1, y1, x2, y2, lw=2, c="k", ls="-", z=2):
        ax.plot([x1, x2], [y1, y2], color=c, lw=lw, ls=ls, solid_capstyle="butt", zorder=z)
    def dot(x, y, r=0.07, c="k"):
        ax.add_patch(Circle((x, y), r, color=c, zorder=5))
    def tierra(x, y, c="k", k=1.0):
        L(x, y, x, y - 0.2 * k, c=c)
        for i, w in enumerate([0.4, 0.26, 0.12]):
            L(x - w * k, y - 0.2 * k - 0.12 * k * i, x + w * k, y - 0.2 * k - 0.12 * k * i, c=c)
    low = [0.0]
    def bajo(y): low[0] = min(low[0], y)

    # ── título y red ─────────────────────────────────────────────────────────
    ax.text(W / 2, 1.3, f"DIAGRAMA UNIFILAR – MEDIDA {tipo.upper()} {SIS_MAY}" + (f" {kv_es}" if kv_es else ""),
            ha="center", fontsize=15, fontweight="bold")
    sub = f"{n_tot} transformadores · " + ("en paralelo" if conf == "paralelo" else "independientes")
    ax.text(W / 2, 0.85, sub, ha="center", fontsize=10, color="#555")
    x_l, x_r = min(cols[0], XC) - 1.2, max(cols[-1], XC) + 1.2
    L(x_l, 0, x_r, 0, lw=5)
    ax.text(W / 2, 0.3, "RED DE DISTRIBUCIÓN" + (f" {volts_pto}" if volts_pto else " M.T.") + f" – {fases}",
            ha="center", fontsize=11, fontweight="bold")

    # ── entrada MT: pararrayos (derivación) ──────────────────────────────────
    y = -1.0
    L(XC, 0, XC, y)
    L(XC, -0.5, XC + 1.4, -0.5, c=VERDE, lw=1.6)
    ax.add_patch(Rectangle((XC + 1.26, -1.4), 0.28, 0.6, fc="white", ec=VERDE, lw=2, zorder=4))
    ax.annotate("", xy=(XC + 1.4, -1.28), xytext=(XC + 1.4, -0.92), arrowprops=dict(arrowstyle="-|>", lw=1.6, color=VERDE))
    L(XC + 1.4, -0.5, XC + 1.4, -0.8, c=VERDE, lw=1.6)
    tierra(XC + 1.4, -1.4, c=VERDE, k=0.8)
    ax.text(XC + 1.75, -1.1, "Pararrayos ZnO" + (f"\n(banco de {dps_n})" if dps_n > 1 else ""),
            ha="left", va="center", fontsize=10, fontweight="bold", color=VERDE)

    # ── medida: TC (+TP) con BLOQUE DE PRUEBAS y medidor(es) a la izquierda ──
    rm = 0.6 if respaldo else 0.75
    def sec(rel, u):
        parte = rel.split("/")[-1].strip() if "/" in rel else ""
        return f"{parte} {u}" if re.fullmatch(r"\d+(?:[.,]\d+)?", parte) else ""
    sec_tc, sec_tp = sec(rel_tc, "A"), sec(rel_tp, "V")
    def medida(X, y_tc, con_tp):
        """TC sobre el conductor X en y_tc; si con_tp, derivacion del TP a la derecha. Devuelve la y
        mas baja del grupo. Los secundarios (punteados) pasan por el bloque de pruebas."""
        ax.add_patch(Circle((X, y_tc), 0.32, fill=False, ec=ROJO, lw=2.6, zorder=6))
        ax.text(X + 0.55, y_tc, f"{n_tc} × TC  {rel_tc + ' A' if rel_tc else '---'}", ha="left", va="center",
                fontsize=11, fontweight="bold", color=ROJO)
        y_tp = y_tc - 2.0 if con_tp else None
        if con_tp:
            xt = X + 3.7
            dot(X, y_tc - 1.2); L(X, y_tc - 1.2, xt, y_tc - 1.2); L(xt, y_tc - 1.2, xt, y_tc - 1.45)
            for dy in (0.55, 1.05):
                ax.add_patch(Circle((xt, y_tc - 1.2 - dy), 0.3, fc="white", ec=AZUL, lw=2.4, zorder=4))
            L(xt, y_tc - 2.55, xt, y_tc - 3.1); tierra(xt, y_tc - 3.1, c=VERDE)
            ax.text(xt, y_tc - 3.95, f"{n_tp} × TP\n{rel_tp + ' V' if rel_tp else '---'}", ha="center", va="center",
                    fontsize=11, fontweight="bold", color=AZUL)
        y_m = y_tc - 1.0
        bx0, bx1 = X - 2.35, X - 1.3
        yb0 = (y_tp - 0.55) if con_tp else (y_tc - 1.8)        # el rotulo vertical mide ~1,9
        ax.add_patch(Rectangle((bx0, yb0), bx1 - bx0, (y_tc + 0.55) - yb0, fc="white", ec="k", lw=2, zorder=3))
        ax.text((bx0 + bx1) / 2, (yb0 + y_tc + 0.55) / 2, "BLOQUE DE PRUEBAS", rotation=90, ha="center",
                va="center", fontsize=9, fontweight="bold", zorder=6)
        L((bx0 + bx1) / 2, yb0, (bx0 + bx1) / 2, yb0 - 0.2, c=VERDE, lw=1.4)
        tierra((bx0 + bx1) / 2, yb0 - 0.2, c=VERDE, k=0.7)
        ax.text((bx0 + bx1) / 2, yb0 - 0.65, "secundarios\na tierra", ha="center", va="top",
                fontsize=8, color=VERDE, fontweight="bold")
        mxs = [X - 4.55, X - 3.2] if respaldo else [X - 3.95]
        for k, mx in enumerate(mxs):
            ax.add_patch(Circle((mx, y_m), rm, fc="white", ec="k", lw=2, zorder=4))
            if respaldo:
                ax.text(mx, y_m + 0.3, "MED1" if k == 0 else "MED2", ha="center", va="center", fontsize=6.5,
                        fontweight="bold", zorder=6)
                ax.text(mx, y_m - 0.1, "kWh\nkVArh", ha="center", va="center", fontsize=8, fontweight="bold", zorder=6)
            else:
                ax.text(mx, y_m + 0.3, "MED1", ha="center", va="center", fontsize=8, fontweight="bold", zorder=6)
                ax.text(mx, y_m - 0.15, "kWh\nkVArh", ha="center", va="center", fontsize=9, fontweight="bold", zorder=6)
        y_lbl = (y_tp - 0.4) if con_tp else (y_m - rm - 0.15)
        ax.text(sum(mxs) / len(mxs), y_lbl, med_txt + f"\n(medida {tipo})", ha="center", va="top",
                fontsize=9.5, fontweight="bold")
        if sec_tc:
            L(X - 0.32, y_tc, bx1, y_tc, lw=1.7, c=ROJO, ls="--"); L(bx0, y_tc, min(mxs), y_tc, lw=1.7, c=ROJO, ls="--")
            ax.text((bx1 + 0.4) if (celda and celda["existe"] is True and medida_mt) else (bx1 + X - 0.32) / 2,
                    y_tc + 0.12, f"Sec. TC\n{sec_tc}", ha="center", va="bottom", fontsize=9, color=ROJO, fontweight="bold")
        for mx in mxs:
            L(mx, y_tc, mx, y_m + rm, lw=1.7, c=ROJO, ls="--")
            if con_tp: L(mx, y_tp, mx, y_m - rm, lw=1.7, c=AZUL, ls="--")
        if con_tp:
            L(X + 3.4, y_tp, bx1, y_tp, lw=1.7, c=AZUL, ls="--"); L(bx0, y_tp, min(mxs), y_tp, lw=1.7, c=AZUL, ls="--")
            if sec_tp:
                ax.text(X + 1.7, y_tp + 0.12, f"Sec. TP – {sec_tp}", ha="center", fontsize=9, color=AZUL, fontweight="bold")
        if respaldo:
            dot(mxs[1], y_tc, r=0.06, c=ROJO)
            if con_tp: dot(mxs[1], y_tp, r=0.06, c=AZUL)
        bottom = y_lbl - 0.7
        if con_tp: bottom = min(bottom, y_tc - 4.5)
        bajo(bottom)
        return bottom

    celda_rect = None
    y_cur = -1.8
    if medida_mt:
        y_tc = -3.5
        L(XC, -1.0, XC, y_tc)
        fondo = medida(XC, y_tc, con_tp_mt)
        y_next = (y_tc - 4.6) if con_tp_mt else (y_tc - 1.4)
        L(XC, y_tc, XC, y_next)
        if celda and celda["existe"] is True:
            x0c, x1c = XC - 0.5, (XC + 5.3 if con_tp_mt else XC + 3.4)
            y1c, y0c = y_tc + 1.0, y_next + 0.2
            ax.add_patch(Rectangle((x0c, y0c), x1c - x0c, y1c - y0c, fill=False, ec=_VIOLETA, lw=2.2, ls=(0, (6, 3)), zorder=1))
            ax.text(x1c, y1c + 0.1, "CELDA DE MEDIDA" + (f" – {celda['tipo']}" if celda["tipo"] else ""),
                    ha="right", va="bottom", fontsize=9.5, fontweight="bold", color=_VIOLETA)
        elif celda and celda["existe"] is False:
            ax.text(XC + (3.7 if con_tp_mt else 1.6), y_tc - (4.45 if con_tp_mt else 0.9), "Sin celda de medida",
                    ha="center", va="center", fontsize=9, color="#555", style="italic")
        y_cur = y_next
    else:
        L(XC, -1.0, XC, -2.0); y_cur = -2.0

    # ── seccionador ANTES de los trafos (lado MT) ────────────────────────────
    def seccionador(X, yt, yb, etiqueta, abierto):
        dot(X, yt); dot(X, yb)
        if abierto: L(X, yt, X + 0.55, yt - 0.75, lw=2.5)
        else:
            L(X, yt, X, yb, lw=2.5, z=3); L(X, yt, X + 0.3, yt - 0.45, lw=2.5, c="k", z=3)
        ax.text(X + 0.6, (yt + yb) / 2 + 0.1, etiqueta, ha="left", va="center", fontsize=10, fontweight="bold")
    estado = "ABIERTO" if secc_open else "cerrado"
    if secc_pos == "antes":
        L(XC, y_cur, XC, y_cur - 0.4)
        seccionador(XC, y_cur - 0.4, y_cur - 1.3, f"Seccionador {polos}\n" + (kv_es if kv_es else "(lado MT)") + f"\n({estado})", secc_open)
        L(XC, y_cur - 1.3, XC, y_cur - 1.7); y_cur -= 1.7

    # ── barraje MT y columnas FUi -> TRFi ────────────────────────────────────
    y_mt = y_cur - 0.7
    L(XC, y_cur, XC, y_mt)
    L(cols[0] - 0.9, y_mt, cols[-1] + 0.9, y_mt, lw=4.5)
    ax.text(cols[0] - 1.05, y_mt, "BARRAJE MT", ha="right", va="center", fontsize=9, fontweight="bold")
    dot(XC, y_mt, r=0.09)
    y_t1 = y_mt - 2.3; y_t2 = y_t1 - 0.55
    for t, x in zip(trafos, cols):
        k = t["k"]
        L(x, y_mt, x, y_mt - 0.62)
        ax.add_patch(Rectangle((x - 0.13, y_mt - 1.18), 0.26, 0.56, fc="white", ec="k", lw=2, zorder=4))
        L(x, y_mt - 0.62, x, y_mt - 1.18, z=5)
        ax.text(x + 0.3, y_mt - 0.9, f"FU{k}", ha="left", va="center", fontsize=9.5, fontweight="bold")
        L(x, y_mt - 1.18, x, y_t1 + 0.5)
        for yy in (y_t1, y_t2):
            ax.add_patch(Circle((x, yy), 0.5, fc="white", ec="k", lw=2, zorder=4))
        L(x - 0.5, y_t2, x - 1.0, y_t2, c=VERDE, lw=1.6); tierra(x - 1.0, y_t2, c=VERDE)
        kva_t = f"{_kva_txt(t['kva'])} kVA" if t["kva"] is not None else "kVA n.i."
        l3 = " · ".join(p for p in (_tipo_txt(t["tipo"]), "Dyn11" if tri else "") if p)
        ax.text(x + 0.7, (y_t1 + y_t2) / 2 + 0.05, f"TRF{k}\n{kva_t}" + (f"\n{l3}" if l3 else ""),
                ha="left", va="center", fontsize=9.5, fontweight="bold")
        if t["uso"] == "compartido":
            ax.text(x + 0.7, y_t2 - 0.72, "COMPARTIDO", ha="left", va="center", fontsize=7.5, fontweight="bold",
                    color="#E65100", bbox=dict(boxstyle="round,pad=0.18", fc="#FFF3E0", ec="#E65100", lw=1.2), zorder=6)
            yb_ = y_t2 - 1.65
            L(x, yb_, x + 1.7, yb_, c=GRIS, lw=1.8, ls=":")
            ax.annotate("", xy=(x + 1.8, yb_), xytext=(x + 1.5, yb_), arrowprops=dict(arrowstyle="-|>", lw=1.4, color=GRIS))
            dot(x, yb_, r=0.07, c=GRIS)
            ax.text(x + 0.15, yb_ - 0.12, "Ramal de otro usuario", ha="left", va="top", fontsize=7.5, color="#666")
    if extra > 0:
        ax.text(cols[-1] + 1.2, y_mt, f"+{extra} transformador{'es' if extra > 1 else ''} no mostrado{'s' if extra > 1 else ''}",
                ha="left", va="center", fontsize=8.5, style="italic", color="#B26A00")

    # ── lado BT ──────────────────────────────────────────────────────────────
    y_bt = y_t2 - 3.1
    def bt_stem(X, y_top, medido, gris=False, nombre="1"):
        """Del barraje BT: [TC | MED1 en linea] -> BKR -> [seccionador] -> carga. Devuelve y del nodo de carga."""
        c = GRIS if gris else "k"; ls = ":" if gris else "-"
        y = y_top
        if medido and medida_bt_tc:
            y_tc = y - 1.3
            L(X, y, X, y_tc, c=c)
            fondo = medida(X, y_tc, tipo == "indirecta")
            y = (y_tc - 4.6) if tipo == "indirecta" else (y_tc - 1.6)
            L(X, y_tc, X, y)
        elif medido and medida_bt_directa:
            y_c = y - 1.4
            L(X, y, X, y_c + 0.55)
            ax.add_patch(Circle((X, y_c), 0.55, fc="white", ec="k", lw=2, zorder=4))
            ax.text(X, y_c, "MED1", ha="center", va="center", fontsize=8, fontweight="bold", zorder=6)
            L(X, y_c - 0.55, X, y_c - 1.1)
            ax.text(X - 0.8, y_c, f"kWh / kVArh\n{med_txt.splitlines()[0]}", ha="right", va="center", fontsize=8.5, fontweight="bold")
            y = y_c - 1.1
        else:
            L(X, y, X, y - 0.9, c=c, ls=ls); y -= 0.9
        yb = y - 0.7
        L(X, y, X, yb + 0.25, c=c, ls=ls)
        ax.add_patch(Rectangle((X - 0.25, yb - 0.25), 0.5, 0.5, fc="white", ec=c, lw=2, zorder=4))
        ax.text(X + 0.55, yb, f"BKR{nombre}" + (f"\n{prot}" if (prot and not gris) else ""), ha="left", va="center",
                fontsize=9.5, fontweight="bold", color="#666" if gris else "k")
        y = yb - 0.25
        if secc_pos == "despues" and not gris:
            L(X, y, X, y - 0.4)
            seccionador(X, y - 0.4, y - 1.3, f"Seccionador {polos}\n(lado BT)\n({estado})", secc_open)
            L(X, y - 1.3, X, y - 1.7); y -= 1.7
        y_n = y - 0.9
        L(X, y, X, y_n - 0.4, c=c, ls=ls)
        ax.add_patch(Polygon([[X - 0.4, y_n - 0.4], [X + 0.4, y_n - 0.4], [X, y_n - 1.1]], closed=True, fill=False,
                             ec=c, lw=2.2, ls=ls))
        ax.text(X, y_n - 1.25, "CARGA" + (f" {nombre}" if conf == "independientes" else ""), ha="center", va="top",
                fontsize=9.5, fontweight="bold", color="#666" if gris else "k")
        bajo(y_n - 1.9)
        return y_n

    if conf == "paralelo":
        for t, x in zip(trafos, cols):
            L(x, y_t2 - 0.5, x, y_bt)
        L(cols[0] - 0.9, y_bt, cols[-1] + 0.9, y_bt, lw=4.5)
        ax.text(cols[-1] + 1.05, y_bt, "BARRAJE BT\n(común)", ha="left", va="center", fontsize=9, fontweight="bold")
        y_nodo = bt_stem(XC, y_bt, True)
        nodo_x = XC
    else:
        nodo_x = cols[0]
        y_nodo = None
        for j, (t, x) in enumerate(zip(trafos, cols)):
            L(x, y_t2 - 0.5, x, y_bt, c="k" if (j == 0 or medida_mt) else GRIS, ls="-" if (j == 0 or medida_mt) else ":")
            gris_ = (j > 0 and not medida_mt)
            L(x - 0.9, y_bt, x + 0.9, y_bt, lw=4.5, c=GRIS if gris_ else "k")
            ax.text(x + 1.0, y_bt + 0.25, f"BT{t['k']}", ha="left", va="center", fontsize=8.5, fontweight="bold",
                    color="#666" if gris_ else "k")
            yn = bt_stem(x, y_bt, medido=(j == 0 and not medida_mt), gris=gris_, nombre=str(t["k"]))
            if j == 0: y_nodo = yn
        if not medida_mt and n > 1:
            ax.text(cols[1] + 0.1, y_bt - 0.7, "(fuera de esta frontera)", ha="left", va="top", fontsize=7.5,
                    color="#666", style="italic")

    # ── planta de respaldo: del lado carga, DESPUES de BKR1 y de la medida ───
    if planta:
        x_borde, y_lbl = _planta_simbolo(ax, nodo_x, y_nodo, planta, 1.0, -1, 1.0)
        bajo(y_lbl)

    # ── ficha técnica ────────────────────────────────────────────────────────
    sumar = [t["kva"] for t in trafos_all] if conf == "paralelo" else [trafos[0]["kva"]]
    kva_clas = sum(k for k in sumar if k is not None)
    filas = [("b", f"Medida {tipo} {sis_adj} – {n_elem} elemento{'s' if n_elem != 1 else ''}"
                   + (" (Aron)" if sistema == "tri3h" else "") + (" · Principal + Respaldo" if respaldo else ""))]
    l2 = [f"Transformadores: {_resumen_trafos(trafos_all)}",
          "Configuración: " + ("en paralelo" if conf == "paralelo" else "independientes")]
    if rel_tc: l2.append(f"TC: {rel_tc} A")
    if rel_tp: l2.append(f"TP: {rel_tp} V")
    l3 = []
    if kv_es: l3.append(f"Red: {kv_es}")
    if circuito: l3.append(f"Circuito: {circuito}")
    if trafos_all and ub == "BT": l3.append("Punto de medición: lado BT del transformador")
    elif trafos_all and ub == "MT" and tipo != "directa": l3.append("Punto de medición: lado MT (antes de los transformadores)")
    if celda and celda["existe"] is True:
        l3.append("Celda de medida: " + " · ".join(p for p in (celda["tipo"], celda["estado"]) if p) if (celda["tipo"] or celda["estado"]) else "Celda de medida: sí")
    elif celda and celda["existe"] is False and medida_mt:
        l3.append("Sin celda de medida")
    if planta:
        l3.append("Planta de respaldo: Sí" + (f" ({_kva_txt(planta['kva'])} kVA)" if planta["kva"] is not None else "")
                  + (f" · transferencia {planta['transf_txt']}" if planta["transf"] else ""))
    if secc_pos == "antes": l3.append("Seccionador MT – " + estado)
    elif secc_pos == "despues": l3.append("Seccionador BT – " + estado)
    if prot: l3.append(f"Protección: {prot}")
    if calibre: l3.append(f"Calibre: {calibre}")
    if kva_clas > 0:
        tcl, mva = _clasif_creg(kva_clas)
        l3.append(f"Clasificación CREG 038: Tipo {tcl} ({_es(mva, 2)} MVA"
                  + (" = suma de los transformadores en paralelo)" if conf == "paralelo" and n_tot > 1 else ")"))
    if extra > 0: l3.append(f"+{extra} transformador{'es' if extra > 1 else ''} no mostrado{'s' if extra > 1 else ''} en el diagrama")
    SEP = "   |   "
    filas.append(("n", SEP.join(l2)))
    linea = ""
    for item in l3:
        if linea and len(linea) + len(SEP) + len(item) > 100:
            filas.append(("n", linea)); linea = item
        else:
            linea = (linea + SEP + item) if linea else item
    if linea: filas.append(("n", linea))
    if tipo == "indirecta" and medida_mt and kva_clas > 0:
        for nivel, corto, _l in _validar_indirecta(dict(cfg, trafo_kva=f"{kva_clas:g}", instalacion="trafo")):
            filas.append((nivel, {"ok": "✓ ", "warn": "⚠ ", "err": "✗ "}[nivel] + corto))
    filas.append(("i", f"Referencia: CREG 038/2014 · RETIE 2024 · Bornera {norma}"))
    cuadro_h = 0.3 + 0.4 * len(filas)
    ct = low[0] - 0.7
    ax.add_patch(Rectangle((0.4, ct - cuadro_h), W - 0.8, cuadro_h, fc="white", ec="k", lw=2))
    col = {"ok": "#2E7D32", "warn": "#B26A00", "err": "#C62828"}
    yy = ct - 0.3
    for kind, txt in filas:
        ax.text(0.7, yy, txt, fontsize=9 if kind == "i" else 10, va="center",
                fontweight="bold" if kind in ("b", "err") else "normal",
                style="italic" if kind == "i" else "normal", color=col.get(kind, "black"))
        yy -= 0.4
    y_fin = ct - cuadro_h - 0.3
    ax.set_xlim(0, W); ax.set_ylim(y_fin, 2.0)
    fig.set_size_inches(W, 2.0 - y_fin)
    plt.savefig(out_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path

# ============================================================
#  UNIFILAR HORIZONTAL: MEDIDA DIRECTA EN GABINETE COMPARTIDO
#  (plano pedido por el usuario con un ejemplo: subestacion -> acometida BT ->
#   gabinete con varios medidores -> ESTE medidor resaltado -> totalizador -> carga)
# ============================================================
_GAB_MAX_OTROS = 12      # posiciones "otro usuario" dibujadas (si hay mas: "+N medidores mas")
_GRIS_G = "#808080"
_AZUL_G = "#5E93CF"

def _gabinete_compartido(cfg):
    """True si el unifilar debe usar el plano horizontal de gabinete compartido: medida DIRECTA
    cuyo punto de conexion lo comparten varios usuarios (trafo_uso='compartido' o hay otros usuarios)."""
    if cfg.get("tipo", "directa") != "directa":
        return False
    if str(cfg.get("trafo_uso", "") or "").lower() == "compartido":
        return True
    try:
        return int(float(cfg.get("trafo_n_usuarios") or 0)) > 0
    except (TypeError, ValueError):
        return False

# tension linea-neutro habitual para cada tension de linea (sistemas trifasicos 4 hilos)
_LN_STD = {208: 120, 220: 127, 380: 220, 400: 230, 440: 254, 460: 265, 480: 277, 600: 347}

_LL_DE_LN = {120: 208, 127: 220, 230: 400, 254: 440, 265: 460, 277: 480, 347: 600}

def _bt_texto(cfg, sistema, medida=None):
    """(texto de la tension secundaria, asumida): '220-127 V', '208-120 V'... Sin dato se asume
    una tension habitual del sistema y se marca como asumida (el plano lo avisa en una nota).
    `sistema` es el del BARRAJE (lo fija el transformador); `medida` el de la medida si es otro
    (trafo trifasico + medida mono/bifasica): un valor suelto de 120/127 V es entonces la tension
    fase-neutro del secundario trifasico ('120' -> '208-120 V')."""
    raw = str(cfg.get("tension_bt") or cfg.get("v_bt") or "").strip()
    if not raw:
        t = str(cfg.get("tension", "") or "")
        if t and not re.search(r"kv", t, re.I):
            raw = t
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", raw)]
    nums = [n for n in nums if 50 <= n <= 1000]
    tri = sistema in ("tri3h", "tri4h")
    if nums:
        ll = nums[0]
        if len(nums) >= 2:                                     # '208/120', '220/127'
            return f"{ll:g}-{nums[1]:g} V", False
        if tri:
            if medida and medida not in ("tri3h", "tri4h") and int(round(ll)) in _LL_DE_LN:
                ll = _LL_DE_LN[int(round(ll))]
            ln = _LN_STD.get(int(round(ll))) or int(round(ll / math.sqrt(3)))
            return (f"{ll:g}-{ln} V" if sistema == "tri4h" else f"{ll:g} V"), False
        if sistema == "bifasico":
            return (f"{ll:g}-{ll / 2:g} V" if int(ll) == 240 else f"{ll:g} V"), False
        return f"{ll:g} V", False
    return {"tri4h": "208-120 V", "tri3h": "208 V", "bifasico": "240-120 V", "mono": "120 V"}.get(sistema, "208-120 V"), True

_GAB_UPI = 12.9      # unidades de dibujo por pulgada del ejemplo (ejes por defecto de subplots + bbox tight)

def _ancho_u(txt, fs, bold=False):
    """Ancho (unidades de dibujo) de la linea mas larga de `txt` a `fs` puntos."""
    from matplotlib.textpath import TextPath
    from matplotlib.font_manager import FontProperties
    fp = FontProperties(weight="bold" if bold else "normal")
    return max((TextPath((0, 0), ln, size=fs, prop=fp).get_extents().width for ln in txt.split("\n") if ln),
               default=0.0) / 72.0 * _GAB_UPI

def _bajante_lineas(bajante):
    """Rotulo del bajante MT. 'monopolar' / 'tripolar' (o con su formacion) -> 'Bajante en cable / monopolar (3 × 1/C)'."""
    bajante = re.sub(r"^\s*(?:en\s+)?(?:cable\s+)?", "", bajante or "", flags=re.IGNORECASE)
    low = bajante.lower()
    if "monopolar" in low:
        return ["Bajante en cable", bajante if "(" in bajante else "monopolar (3 × 1/C)"]
    if "tripolar" in low:
        return ["Bajante en cable", bajante if "(" in bajante else "tripolar (1 × 3/C)"]
    return [f"Bajante: {bajante}"] if bajante else ["Bajante MT"]

def draw_unifilar_gabinete(cfg, out_path):
    """Unifilar HORIZONTAL de medida directa en un punto/gabinete COMPARTIDO (el plano del ejemplo
    "unifilar_medida_directa"): red MT -> [seccionador MT] -> transformador (con SPT) -> acometida BT ->
    gabinete de medida con barraje BT, ESTE medidor en recuadro azul (medidor -> totalizador -> carga) y
    las posiciones de los otros usuarios (punteadas). Lo que no se sabe (kVA del trafo, amperaje del
    totalizador, clase del medidor) se rotula "___ (por definir)" y se lista en NOTAS: nunca se inventa.
    Sin transformador (instalacion != 'trafo') se omite la subestacion y la acometida BT entra por la
    izquierda. Mismas coordenadas, tamanos de letra y textos que el script del ejemplo (~12,9 unidades
    = 1 pulgada), ancho segun el numero de medidores, alto 110 u (mas las notas). Unico retoque respecto al
    ejemplo: rotulos que ahi cruzaban una linea (SUBESTACION / SPT) o un borde (rotulos del medidor)."""
    sistema = cfg.get("sistema", "tri4h")
    if sistema not in _SIS_PRO: sistema = "tri4h"
    tri = sistema in ("tri3h", "tri4h")
    hilos = {"mono": "monofásica 2 hilos", "bifasico": "bifásica 3 hilos", "tri3h": "trifásica 3 hilos",
             "tri4h": "trifásica 4 hilos"}[sistema]
    med_adj = {"mono": "monofásico", "bifasico": "bifásico", "tri3h": "trifásico", "tri4h": "trifásico"}[sistema]
    norma = cfg.get("norma", "RA8")
    kv = _kv_de(cfg.get("v_mt"))
    kv_es = (f"{kv:g}".replace(".", ",") + " kV") if kv else ""
    con_trafo = cfg.get("instalacion") == "trafo"

    # El TRANSFORMADOR y la MEDIDA tienen fases independientes: un trafo trifasico puede alimentar un medidor
    # mono o bifasico. `sistema` es el de la medida (ramal de ESTE usuario); `sis_bus` el del barraje BT y de la
    # acometida, que lo fija el trafo. Sin `trafo_tipo` se asume igual al de la medida (y una nota lo avisa).
    tt = {"trifasico": "trifasico", "monofasico": "monofasico", "bifasico": "bifasico"}.get(
        str(cfg.get("trafo_tipo") or "").strip().lower(), "")
    sis_bus, nota_fases = sistema, []
    if con_trafo and tt:
        sis_bus = {"trifasico": "tri3h" if sistema == "tri3h" else "tri4h", "bifasico": "bifasico",
                   "monofasico": "bifasico" if sistema == "bifasico" else "mono"}[tt]      # mono + punto medio = 2F + N
        if tri and sis_bus not in ("tri3h", "tri4h"):         # una medida trifasica no sale de un trafo mono/bifasico
            nota_fases.append(f"Un transformador {tt.replace('fasico', 'fásico')} no alimenta una medida trifásica: se dibujó el transformador trifásico.")
            sis_bus, tt = sistema, "trifasico"
    tri_t = sis_bus in ("tri3h", "tri4h")                    # el transformador es trifasico
    nf = {"mono": 1, "bifasico": 2, "tri3h": 3, "tri4h": 3}[sis_bus]            # marcas de conductores del barraje
    nf_m = {"mono": 1, "bifasico": 2, "tri3h": 3, "tri4h": 3}[sistema]          # ... y del ramal de la medida
    nf_mt = {"trifasico": 3, "bifasico": 2, "monofasico": 1}.get(tt, nf)         # ... y del bajante MT
    f_txt = {"mono": "1F + N + PE", "bifasico": "2F + N + PE", "tri3h": "3F + PE", "tri4h": "3F + N + PE"}[sis_bus]
    bus_txt = {"mono": "(1F + N)", "bifasico": "(2F + N)", "tri3h": "(3F)", "tri4h": "(3F + N)"}[sis_bus]
    f_med = {"mono": "1F + N", "bifasico": "2F + N", "tri3h": "3F", "tri4h": "3F + N"}[sistema]
    fases_dif = con_trafo and bool(tt) and f_med != bus_txt.strip("()")     # el medidor toma solo parte del barraje
    sis_dif = sis_bus != sistema
    gab = cfg.get("trafo_gabinete")
    gab_si = gab is True
    respaldo = bool(cfg.get("respaldo", False))
    ubic_t = str(cfg.get("ubicacion_trafo", "") or "").lower()
    if ubic_t not in ("interior", "poste", "exterior", "camara"):
        ubic_t = "interior" if gab_si else ""
    sub_titulo = {"interior": "SUBESTACIÓN INTERIOR"}.get(ubic_t, "SUBESTACIÓN")
    sub_caja = ubic_t in ("interior", "")          # poste / exterior / camara: sin recuadro de subestacion
    sub_sub = {"interior": "Transformador interno", "poste": "Transformador en poste",
               "exterior": "Transformador externo", "camara": "Transformador en cámara"}.get(ubic_t, "")

    # ── datos del punto compartido ────────────────────────────────────────────
    try: otros = max(0, int(float(cfg.get("trafo_n_usuarios") or 0)))
    except (TypeError, ValueError): otros = 0
    otros_def = otros > 0
    total = otros + 1
    if otros_def:
        n_draw = min(total, _GAB_MAX_OTROS + 1)    # posiciones dibujadas (ESTE medidor incluido)
        mas = total - n_draw                       # medidores que no caben: se resumen en la ultima posicion
    else:
        n_draw, mas = 3, 0                         # sin cantidad: ESTE medidor + 2 posiciones de ejemplo
    try: pos = int(float(cfg.get("posicion_medida") or 1))
    except (TypeError, ValueError): pos = 1
    if not otros_def or mas > 0 or not 1 <= pos <= n_draw:
        pos = 1                                    # posicion de ESTE medidor de izquierda a derecha

    # ── elementos opcionales ──────────────────────────────────────────────────
    secc = cfg.get("seccionador", "") if cfg.get("seccionador") in ("antes", "despues") else ""
    secc_open = cfg.get("seccionador_estado") == "abierto"
    p_antes, p_desp = str(cfg.get("proteccion_antes") or "").strip(), str(cfg.get("proteccion_despues") or "").strip()
    p_gen = str(cfg.get("interruptor") or "").strip() or (f"{cfg['proteccion_amp']} A" if cfg.get("proteccion_amp") else "")
    tot_pos = cfg.get("totalizador") if cfg.get("totalizador") in ("antes", "despues") else ""
    if not tot_pos:
        tot_pos = "antes" if (p_antes and not p_desp) else ("despues" if (p_desp or p_gen or p_antes) else "")
    am = _num((p_antes if tot_pos == "antes" else p_desp) or p_gen or p_antes or p_desp)
    amps_txt = f"{am:g} A".replace(".", ",") if am is not None else ""
    pol = _num(cfg.get("interruptor_polos"))
    polos = f"{int(pol)}P" if pol else {"mono": "1P", "bifasico": "2P", "tri3h": "3P", "tri4h": "3P"}[sistema]
    tipo_int = str(cfg.get("interruptor_tipo") or "termomagnético").strip() or "termomagnético"
    if tipo_int.lower().startswith("termomagnetico"): tipo_int = "termomagnético"
    clase = _t1(cfg.get("clase_medidor"), 12)
    bt_txt, bt_asumida = _bt_texto(cfg, sis_bus, sistema if sis_dif else None)
    kva = _num(cfg.get("trafo_kva"))
    kva_txt = f"{_kva_txt(kva)} kVA" if kva is not None else "___ kVA  (por definir)"
    tipo_trafo = {"trifasico": "trifásico", "monofasico": "monofásico", "bifasico": "bifásico"}.get(tt, "trifásico" if tri_t else "")
    bajante = _t1(cfg.get("bajante_mt"), 50)
    planta = _planta_de(cfg)
    circuito = _t1(cfg.get("circuito"), 30)
    proyecto = _t1(cfg.get("proyecto"), 40)
    calibre = _t1(cfg.get("calibre_conductor") or cfg.get("calibre_acometida"), 30)

    cls_txt = f"clase {clase}" if clase else "clase ___"
    kwh = "kWh\nkVArh" if tri else "kWh"
    med_lines = (f"Medidor {med_adj}\ndirecto (sin TC)\n{cls_txt}" if not respaldo else
                 f"Medidores {med_adj}s\ndirectos (sin TC)\nprincipal + respaldo\n{cls_txt}")
    tot_lines = f"Totalizador {tipo_int} {polos}\n" + (amps_txt or "___ A  (por definir)")
    lab_w = max(_ancho_u(med_lines, 9), _ancho_u(tot_lines, 9, bold=True) if tot_pos else 0.0)

    # ── geometria horizontal (coordenadas del ejemplo) ────────────────────────
    lab_acom = "Acometida BT " + f_txt + (f"  –  {calibre}" if calibre else "")
    CX0 = 76.0 if con_trafo else 2.0 + _ancho_u(lab_acom, 9) + 6.0     # borde izquierdo del gabinete
    hw = 16.0 if respaldo else 11.0                # semiancho del recuadro azul (ESTE medidor)
    w_oth = 17.0 if (n_draw - 1) <= 6 else 14.5     # con muchos usuarios las posiciones se juntan un poco
    slots, x = [], CX0 + 12.0
    for i in range(1, n_draw + 1):
        w = (2 * hw + 0.5 + 1.2 + lab_w + 3.0) if i == pos else w_oth
        w = max(w, 42.0) if i == pos else w
        slots.append((i, x, w)); x += w
    CX1 = x + 4.0
    W = max(CX1 + 4.0, 150.0 if con_trafo else 100.0)
    xs = {i: sx + ((hw + 0.5) if i == pos else sw / 2) for i, sx, sw in slots}     # el recuadro azul deja margen a las vecinas
    x0 = xs[pos]                                   # eje del ramal de ESTE usuario
    bx0, bx1 = x0 - hw, x0 + hw
    lab_x = bx1 + 1.2                              # rotulos del ramal: FUERA del recuadro azul
    bus_x0, bus_x1 = CX0 + 6.0, max(xs.values()) + 4.0

    # ── geometria vertical: cadena barraje -> [totalizador] -> medidor(es) -> [totalizador] -> carga ──
    BY = 62.0                                      # nivel del barraje BT
    y = BY - 8.0
    yc_ta = y_ta_bot = None
    if tot_pos == "antes":
        yc_ta = y - 4.0; y_ta_bot = y - 8.0; y = y_ta_bot - 6.0
    r_m = 4.2 if respaldo else 5.0
    if not respaldo:
        yc_m = y - r_m
        y_med_top, y_med_bot = y, y - 2 * r_m
        y_n1 = y_n2 = None
    else:
        y_n1 = y
        yc_m = y_n1 - 4.0 - r_m
        y_med_top = yc_m + r_m
        y_n2 = yc_m - r_m - 4.0
        y_med_bot = y_n2
    y = y_med_bot
    yc_td = y_td_top = y_td_bot = None
    if tot_pos == "despues":
        y_td_top = y - 6.0; yc_td = y_td_top - 4.0; y_td_bot = y_td_top - 8.0; y = y_td_bot
    y_load0 = min(20.0, y - 10.0)
    y_load1 = y_load0 - 6.0
    y_ac = min(14.0, y_load1)                      # horizontal de la acometida BT
    cab_bot = min(6.0, y_load1 - 8.0)
    ytop = 110.0 if con_trafo else 92.0

    # ── notas (se arman antes: su altura decide el alto del lienzo) ───────────
    pend = []
    if con_trafo and kva is None: pend.append("kVA del transformador")
    if not clase:                 pend.append("clase del medidor")
    if tot_pos and am is None:    pend.append(f"amperaje del totalizador {polos}")
    if con_trafo and not kv:      pend.append("tensión MT de la red")
    notas = []
    if pend:
        notas.append("Valores marcados con ___ pendientes de confirmar en campo: " + ", ".join(pend) + ".")
    if bt_asumida:
        notas.append("Tensión BT asumida; verificar " + ("en placa del transformador." if con_trafo else "en la acometida."))
    if tot_pos == "despues":
        notas.append(f"Totalizador {tipo_int} ubicado después del medidor, en el mismo ramal del barraje.")
    elif tot_pos == "antes":
        notas.append(f"Totalizador {tipo_int} ubicado antes del medidor, en el mismo ramal del barraje.")
    if secc == "antes" and con_trafo:
        notas.append(f"Seccionador MT antes del transformador conforme a norma {norma} del operador de red.")
    elif secc == "despues" and con_trafo:
        notas.append("Seccionador en el lado BT, aguas abajo del transformador.")
    if secc and secc_open and con_trafo:
        notas.append("El seccionador se dibuja ABIERTO (instalación desenergizada).")
    notas += nota_fases
    if fases_dif:
        notas.append(f"Transformador {tipo_trafo} y medida {_SIS_PRO[sistema][1]}: el medidor se deriva del barraje BT "
                     f"{bus_txt} con {f_med}; fase(s) de conexión por definir en campo.")
    elif con_trafo and not tt and sistema != "tri4h":
        notas.append(f"Fases del transformador sin indicar: se dibujó según el sistema de la medida ({_SIS_PRO[sistema][1]}). "
                     "Si es trifásico, indícalo.")
    if not otros_def:
        notas.append("Cantidad de usuarios del gabinete por definir: se muestran 2 posiciones de ejemplo.")
    elif mas:
        notas.append(f"El gabinete tiene {total} medidores: se dibujan {n_draw - 1} posiciones de otros usuarios y "
                     f"se resume el resto en la última.")
    try: dps = int(cfg.get("dps_cantidad") or 0)
    except (TypeError, ValueError): dps = 0
    if dps >= 1 and con_trafo:
        notas.append(("Protección contra sobretensiones: " + ("banco de %d pararrayos" % dps if dps > 1 else "pararrayos")
                      + " ZnO (DPS) en la entrada MT (no dibujado en este plano)."))
    if planta:
        notas.append("Planta de respaldo: Sí"
                     + (f" ({_kva_txt(planta['kva'])} kVA)" if planta["kva"] is not None else " (kVA no informado)")
                     + (f", transferencia {planta['transf_txt']}" if planta["transf"] else "")
                     + ". No es medida por este medidor.")
    if cfg.get("tendido") == "subterraneo" and con_trafo:
        notas.append("Acometida MT subterránea.")
    ancho_car = max(60, int((W - 6.0) / 0.84))
    notas_w = ["NOTAS:"]
    for i, n_ in enumerate(notas, 1):
        notas_w += textwrap.wrap(f"{i}. {n_}", ancho_car, subsequent_indent="    ") or [""]
    y_notas = cab_bot - 1.5
    ymin = y_notas - 1.8 * len(notas_w) - 1.5

    fig = plt.figure(figsize=(W / _GAB_UPI, (ytop - ymin) / _GAB_UPI))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(ymin, ytop); ax.axis("off")
    K, LW = "k", 1.8
    def L(xx, yy, lw=LW, c=K, ls="-", z=3):
        ax.plot(xx, yy, color=c, lw=lw, ls=ls, solid_capstyle="butt", zorder=z)
    def T(xx, yy, s, ha="left", va="center", fs=9.0, fw="normal", c=K, st="normal"):
        ax.text(xx, yy, s, ha=ha, va=va, fontsize=fs, fontweight=fw, color=c, style=st, zorder=6)
    def marcas(xx, yy, n=None):                    # marcas de conductores (3 = trifasico) sobre un tramo vertical
        n = nf if n is None else n
        for k in range(n):
            d = (k - (n - 1) / 2) * 1.6
            ax.plot([xx - 1.2, xx + 1.2], [yy + d - 0.9, yy + d + 0.9], color=K, lw=1.3, zorder=5, solid_capstyle="butt")
    def marcas_h(xx, yy):                          # ... y sobre un tramo horizontal
        for k in range(nf):
            d = (k - (nf - 1) / 2) * 1.6
            ax.plot([xx + d - 0.9, xx + d + 0.9], [yy - 1.2, yy + 1.2], color=K, lw=1.3, zorder=5, solid_capstyle="butt")
    def tierra(xx, yy):
        L([xx, xx], [yy, yy - 2])
        for k, w in enumerate((3.5, 2.3, 1.1)):
            L([xx - w, xx + w], [yy - 2 - k * 1.1] * 2)
    def dot(xx, yy): ax.add_patch(Circle((xx, yy), 0.5, color=K, zorder=6))
    def switch(xx, yc, h=8.0):                     # contactos + cuchilla
        L([xx, xx], [yc + h / 2, yc + h / 2 - 2]); L([xx, xx], [yc - h / 2, yc - h / 2 + 2])
        dot(xx, yc + h / 2 - 2); dot(xx, yc - h / 2 + 2)
        L([xx, xx + 2.6], [yc - h / 2 + 2, yc + h / 2 - 2.4], z=6)
    def box(xa_, ya_, w_, h_, c="gray", lw=1.3, ls="--", z=1):
        ax.add_patch(Rectangle((xa_, ya_), w_, h_, fill=False, ls=ls, lw=lw, ec=c, zorder=z))
    def circ(xx, yy, r, lw=LW):
        ax.add_patch(Circle((xx, yy), r, fc="white", ec=K, lw=lw, zorder=4))

    # ── encabezado ────────────────────────────────────────────────────────────
    cnt = f" ({total} MEDIDORES)" if otros_def else ""
    if gab is False:
        titulo = f"DIAGRAMA UNIFILAR – MEDIDA DIRECTA EN PUNTO COMPARTIDO{cnt} – RED ABIERTA"
    else:
        titulo = f"DIAGRAMA UNIFILAR – MEDIDA DIRECTA {'INTERIOR ' if gab_si else ''}EN GABINETE COMPARTIDO{cnt}"
    partes = []
    if con_trafo: partes.append(f"Red MT {kv_es}" if kv_es else "Red MT")
    if sis_dif: partes.append(f"Medida {hilos}")                     # trafo y medida de distinta fase
    elif sistema != "tri4h": partes.append(f"Sistema {hilos}")
    if con_trafo and sub_sub: partes.append(sub_sub)
    partes.append("Barraje común" + (" con totalizador posterior al medidor" if tot_pos == "despues" else
                                     " con totalizador previo al medidor" if tot_pos == "antes" else ""))
    if circuito: partes.append(f"Circuito: {circuito}")
    if proyecto: partes.append(proyecto)
    sub_lin, cur = [], ""
    for p_ in partes:                               # parte el subtitulo en lineas sin dejar "|" al inicio
        cand = (cur + "  |  " + p_) if cur else p_
        if cur and len(cand) > 160: sub_lin.append(cur); cur = p_
        else: cur = cand
    sub_lin.append(cur)
    T(W / 2, ytop - 3.0, titulo, ha="center", fs=13, fw="bold")
    T(W / 2, ytop - 6.5 - 1.8 * (len(sub_lin) - 1) / 2, "\n".join(sub_lin), ha="center", fs=9.5, st="italic")

    # ── red MT + subestacion + acometida BT ───────────────────────────────────
    BT_TOP = 80.0                                  # borde superior de subestacion y gabinete
    if con_trafo:
        T(30, 97, "RED DE DISTRIBUCIÓN MT" + (f"\n{kv_es} – 3F" if kv_es and tri_t else f"\n{kv_es}" if kv_es else ""),
          ha="center", fs=10, fw="bold")
        L([18, 42], [93, 93], lw=3)
        marcas(30, 90.5, nf_mt)
        T(36, 85, "\n".join(_bajante_lineas(bajante) + ([kv_es] if kv_es else [])), fs=9)
        if sub_caja:
            box(10, y_ac + 4.0, 60, BT_TOP - (y_ac + 4.0))
            T(44, 77.5, sub_titulo, ha="center", fs=9, fw="bold", c="gray")
        if secc == "antes":
            L([30, 30], [93, 72]); switch(30, 68); L([30, 30], [64, 56])
            T(46, 68, "Seccionador MT" + f"\n(según norma {norma})" + (f"\n{kv_es} – 3P" if kv_es and tri_t else "")
              + ("\nABIERTO" if secc_open else ""), fs=9)
        else:
            L([30, 30], [93, 56])
        circ(30, 52.5, 4.2, lw=LW); circ(30, 47.5, 4.2, lw=LW)
        T(46, 50, f"Transformador {tipo_trafo}".rstrip() + f"\n{kva_txt}\n"
          + (f"{kv_es} / {bt_txt}" if kv_es else f"MT / {bt_txt}") + ("\n(verificar tensión BT)" if bt_asumida else ""), fs=9)
        if secc == "despues":
            L([30, 30], [43.3, 34.0]); switch(30, 30.0); L([30, 30], [26.0, y_ac])
            T(46, 30, "Seccionador BT" + ("\n3P" if tri_t else "") + ("\nABIERTO" if secc_open else ""), fs=9)
            marcas(30, 38.0)
        else:
            L([30, 30], [43.3, y_ac]); marcas(30, 39.5)
        L([24, 24], [42, 30]); L([24, 30], [42, 42]); tierra(24, 30)
        T(28.6, 22.5, "SPT neutro BT y masas", ha="right", fs=8)
        x_v = CX0 - 3.0                            # subida de la acometida hacia el barraje
        L([30, x_v], [y_ac, y_ac]); L([x_v, x_v], [y_ac, BY]); marcas(x_v, (y_ac + BY) / 2)
        L([x_v, bus_x0], [BY, BY])
        T(34, y_ac - 4.5, lab_acom, fs=9)
    else:
        x_in = 2.0
        L([x_in, bus_x0], [BY, BY]); marcas_h(x_in + 7.0, BY)
        T(x_in, BY + 2.6, lab_acom, fs=9, va="bottom")

    # ── gabinete + barraje ────────────────────────────────────────────────────
    if gab_si:
        box(CX0, cab_bot, CX1 - CX0, BT_TOP - cab_bot)
        tit_cab = (f"GABINETE DE MEDIDA – {total} MEDIDORES (INTERIOR)" if otros_def else "GABINETE DE MEDIDA (INTERIOR)")
    else:
        tit_cab = (f"PUNTO COMPARTIDO – {total} MEDIDORES" if otros_def else "PUNTO COMPARTIDO") + (" (RED ABIERTA)" if gab is False else "")
    T((CX0 + CX1) / 2, 77.5, tit_cab, ha="center", fs=9, fw="bold", c="gray")
    L([bus_x0, bus_x1], [BY, BY], lw=5)
    T(CX0 + 9, BY + 6.2, "Barraje BT\n" + bus_txt, fs=9, fw="bold")

    # ── otros usuarios (punteados en gris) ────────────────────────────────────
    otros_idx = [i for i in range(1, n_draw + 1) if i != pos]
    for k, i in enumerate(otros_idx):
        xo = xs[i]
        ultimo = (k == len(otros_idx) - 1) and mas > 0
        L([xo, xo], [BY, 50])
        box(xo - 6, 38, 12, 12, c="gray", lw=1.2)
        T(xo, 44, (f"+{mas + 1}\nmedidores\nmás" if ultimo else f"Medida\n{i}"), ha="center", fs=8.5, c="gray")
        L([xo, xo], [38, 30], lw=1.2, c="gray", ls="--")
        T(xo, 27, "otros\nusuarios" if ultimo else "otro\nusuario", ha="center", fs=8, c="gray")

    # ── ESTE medidor ──────────────────────────────────────────────────────────
    box(bx0, y_load1 - 3.5, bx1 - bx0, (BY + 2.5) - (y_load1 - 3.5), c="#1f6fb2", lw=1.0, ls="-")
    ax.patches[-1].set_alpha(0.6)
    T(x0, y_load1 - 6.0, "Medida objeto del unifilar", ha="center", fs=8.5, fw="bold", c="#1f6fb2")
    def totalizador(yc):
        switch(x0, yc, h=8.0)
        ax.add_patch(Rectangle((x0 - 1.8, yc - 1), 3.6, 2, fill=False, lw=1, ec=K, zorder=6))
        T(lab_x, yc, tot_lines, fs=9, fw="bold")
    L([x0, x0], [BY, (yc_ta + 4.0) if yc_ta is not None else (y_n1 if respaldo else y_med_top)]); marcas(x0, BY - 4.0, nf_m)
    if fases_dif:
        T(x0 - 2.4, BY - 4.0, f_med, ha="right", fs=7.5, c="#1f6fb2")      # conductores que toma la medida del barraje
    if yc_ta is not None:                          # totalizador ANTES del medidor
        totalizador(yc_ta)
        L([x0, x0], [y_ta_bot, y_n1 if respaldo else y_med_top])
    if not respaldo:
        circ(x0, yc_m, r_m, lw=2.2)
        T(x0, yc_m, kwh, ha="center", fs=8.5, fw="bold")
        T(lab_x, yc_m, med_lines, fs=9)
        y_sale = y_med_bot
    else:
        xm1, xm2 = x0 - 6.5, x0 + 6.5
        L([xm1, xm2], [y_n1, y_n1]); dot(x0, y_n1)
        L([xm1, xm2], [y_n2, y_n2]); dot(x0, y_n2)
        for xm_, et, ha_ in ((xm1, "PRINCIPAL", "right"), (xm2, "RESPALDO", "left")):
            L([xm_, xm_], [y_n1, yc_m + r_m]); circ(xm_, yc_m, r_m, lw=2.0)
            T(xm_, yc_m, "kWh", ha="center", fs=8, fw="bold")
            L([xm_, xm_], [yc_m - r_m, y_n2])
            T(xm_ + (-1.4 if ha_ == "right" else 1.4), yc_m - r_m - 1.9, et, ha=ha_, fs=7, fw="bold", c="#555555")
        T(lab_x, yc_m, med_lines, fs=9)
        y_sale = y_n2
    if yc_td is not None:                          # totalizador DESPUES del medidor
        L([x0, x0], [y_sale, yc_td + 4.0]); totalizador(yc_td)
        y_sale = y_td_bot
    L([x0, x0], [y_sale, y_load0])
    if y_sale - y_load0 >= 6.0: marcas(x0, (y_sale + y_load0) / 2 - 1.0, nf_m)
    ax.add_patch(Rectangle((bx0, y_load1), bx1 - bx0, y_load0 - y_load1, fc="white", ec=K, lw=2, zorder=4))
    T(x0, (y_load0 + y_load1) / 2, "CARGA DEL USUARIO", ha="center", fs=9, fw="bold")

    # ── notas ─────────────────────────────────────────────────────────────────
    for i, linea in enumerate(notas_w):
        T(2, y_notas - 1.8 * i, linea, va="top", fs=8.2, fw="bold" if i == 0 else "normal")
    plt.savefig(out_path, dpi=140, facecolor="white")
    plt.close(fig)


def draw_unifilar_generico(cfg, out_path):
    """
    Topologia vertical principal. TC/TP como ramas horizontales hacia la derecha.
    BLOQUE DE PRUEBA + MEDIDOR como cajas prominentes a la derecha del eje.
    Proteccion configurable: antes del medidor, despues, o ambas.

    Medida INDIRECTA con un solo trafo (o sin trafo) se dibuja con el estilo
    "plano limpio" de draw_unifilar_indirecta_pro. Quedan en este renderer: las
    subestaciones multi-celda (n_trafos>=2), directa/semidirecta, y indirecta
    con cfg["estilo"] == "detallado" (CC fusibles, pararrayos, bloque de prueba
    y plano de simbologia).
    """
    if isinstance(cfg.get("transformadores"), (list, tuple)) and len(_trafos_de(cfg)) >= 2:
        return draw_unifilar_frontera(cfg, out_path)      # 2+ transformadores (campos de acta)
    if _gabinete_compartido(cfg):
        return draw_unifilar_gabinete(cfg, out_path)      # medida directa en gabinete compartido
    try:
        _n_tr = int(cfg.get("n_trafos", 1) or 1)
    except (TypeError, ValueError):
        _n_tr = 1
    if cfg.get("tipo") == "indirecta" and cfg.get("estilo") != "detallado" and _n_tr < 2:
        return draw_unifilar_indirecta_pro(cfg, out_path)
    tipo        = cfg.get("tipo", "directa")
    sistema     = cfg.get("sistema", "tri4h")
    norma       = cfg.get("norma", "RA8")
    rel_tc      = cfg.get("rel_tc", "")
    rel_tp      = cfg.get("rel_tp", "")
    # "" (o no especificado) = sin trafo NI barraje explicito -- acometida
    # directa desde la red BT (el caso mas simple, tipico de una conexion
    # residencial). Antes esto se coaccionaba a "barraje", asi que CUALQUIER
    # especificacion de texto libre sin mencion de transformador (la mas
    # comun de todas) terminaba rotulada "BARRAJE B.T." sin que el usuario
    # hubiera dicho nada de un barraje -- ver seccion FUENTE/ENTRADA abajo.
    instalacion = cfg.get("instalacion") or ""
    trafo_uso   = cfg.get("trafo_uso", "")   # "exclusivo" | "compartido" | ""
    es_compartido = (instalacion == "trafo" and trafo_uso == "compartido")
    bt_y = None       # nivel del barraje BT compartido (se fija mas abajo si aplica)
    gabinete = False  # True = encerrar barraje+medidores en un recinto (gabinete cerrado)
    respaldo    = bool(cfg.get("respaldo", False))
    kva         = cfg.get("trafo_kva", "")
    trafo_tipo  = cfg.get("trafo_tipo", "trifasico")
    n_trafos    = int(cfg.get("n_trafos", 1))
    # Subestacion con VARIAS celdas de transformacion INDEPENDIENTES (cada una
    # con su propia proteccion y su propia carga aguas abajo), colgando de una
    # barra de distribucion comun despues del punto de medida MT. Distinto del
    # "banco" de transformadores monofasicos en paralelo (que sigue existiendo
    # para semidirecta/directa: 3 unidades formando UN solo trafo trifasico
    # para UNA sola carga) -- aqui cada TRi es un trafo separado con su propia
    # salida. Solo aplica a indirecta (medida en MT de una subestacion).
    es_multi_celda = (tipo == "indirecta" and instalacion == "trafo" and n_trafos >= 2)
    # Proteccion: antes del medidor, despues, o ninguna
    prot_antes   = cfg.get("proteccion_antes", "")
    prot_despues = cfg.get("proteccion_despues", "")
    # Compatibilidad con campo anterior 'interruptor'
    interruptor_old = cfg.get("interruptor", "")
    if interruptor_old and not prot_antes and not prot_despues:
        if tipo == "directa":
            prot_antes = interruptor_old
        else:
            prot_despues = interruptor_old
    interruptor_medida = bool(cfg.get("interruptor_medida", False))
    seccionador_pos  = cfg.get("seccionador", "")
    calibre          = cfg.get("calibre_conductor", "") or cfg.get("calibre_acometida", "")
    planta_g, celda_g, ubic_g = _planta_de(cfg), _celda_de(cfg), _ubic_medida(cfg)

    tipo_txt = {"directa":"Directa","semidirecta":"Semidirecta","indirecta":"Indirecta"}[tipo]
    sis_short = SIS_TXT[sistema].split(" (")[0].title()

    # ── Datos del CUADRO DE DATOS (columna derecha, sobre el plano de ─────────
    # simbologia). Se arman ANTES de crear la figura porque su altura decide
    # cuanto crece el lienzo. Solo se listan cosas que SI quedan dibujadas: un
    # cuadro que diga "seccionador" cuando no se dibujo seria peor que no
    # tener cuadro.
    # Lado del seccionador: "antes" (del trafo) siempre es MT; "despues" es BT
    # salvo indirecta sin trafo (no hay trafo que separe MT de BT).
    secc_dibujado = (not es_multi_celda) and (
        seccionador_pos == "despues" or (seccionador_pos == "antes" and instalacion == "trafo"))
    secc_lado = "MT" if (seccionador_pos == "antes" or
                         (tipo == "indirecta" and instalacion != "trafo")) else "BT"
    # Estado: CERRADO por defecto (posicion normal de servicio: la instalacion se
    # lee energizada); cfg["seccionador_estado"]="abierto" corta el conductor.
    secc_abierto = cfg.get("seccionador_estado") == "abierto"
    secc_estado_txt = "ABIERTO" if secc_abierto else "cerrado"
    v_mt_cfg = cfg.get("v_mt", "")
    prot_antes_ef = prot_antes if tipo in ("directa", "semidirecta") else ""
    prot_desp_ef  = "" if es_multi_celda else prot_despues

    def _prot_txt(amp):
        polos, tprot = cfg.get("interruptor_polos"), cfg.get("interruptor_tipo")
        return "  ".join(p for p in (amp, f"{polos}P" if polos else None, tprot) if p)

    filas = [("Medida", f"{tipo_txt} · {sis_short}" + (" · Principal + Respaldo" if respaldo else ""))]
    if instalacion == "trafo":
        kva_l = [str(k) for k in (cfg.get("trafo_kva_list") or [])]
        lista = " + ".join(kva_l) if kva_l else str(kva or "")
        if es_multi_celda:
            t_txt = f"{n_trafos} celdas" + (f": {lista} kVA" if lista else "")
        elif n_trafos >= 2:
            t_txt = f"banco de {n_trafos}" + (f": {lista} kVA" if lista else "")
        else:
            t_txt = " ".join(p for p in (f"{kva} kVA" if kva else "", trafo_tipo) if p)
        if trafo_uso == "compartido":
            n_us = str(cfg.get("trafo_n_usuarios", "") or "").strip()
            t_txt += " · compartido" + (f" ({n_us} usuarios más)" if n_us else "")
        elif trafo_uso == "exclusivo":
            t_txt += " · exclusivo"
        filas.append(("Transformador", t_txt))
    elif instalacion == "barraje":
        t_bt = cfg.get("tension_bt", "")
        filas.append(("Barraje BT", f"{t_bt} V" if t_bt else "B.T."))
    if v_mt_cfg and (tipo == "indirecta" or instalacion == "trafo"):
        filas.append(("Tensión MT", v_mt_cfg))
    if rel_tc or rel_tp:
        filas.append(("Relaciones", "  ·  ".join(
            x for x in (f"TC {rel_tc}" if rel_tc else "", f"TP {rel_tp}" if rel_tp else "") if x)))
    if secc_dibujado:
        filas.append(("Seccionador",
                      ("antes del trafo" if seccionador_pos == "antes" else "después del trafo")
                      + f" (lado {secc_lado}"
                      + (f" {v_mt_cfg}" if secc_lado == "MT" and v_mt_cfg else "") + f") · {secc_estado_txt}"))
    prot_partes = []
    if prot_antes_ef: prot_partes.append(f"{_prot_txt(prot_antes_ef)} (antes del medidor)")
    if prot_desp_ef:  prot_partes.append(f"{_prot_txt(prot_desp_ef)} (después)")
    if prot_partes:
        filas.append(("Protección", " · ".join(prot_partes)))
    if calibre:
        filas.append(("Calibre", calibre))
    if ubic_g == "BT" and instalacion == "trafo":
        filas.append(("Punto de medición", "lado BT del transformador"))
    if celda_g and (celda_g["existe"] is True or celda_g["tipo"] or celda_g["estado"]):
        filas.append(("Celda de medida", " · ".join(p for p in (celda_g["tipo"], celda_g["estado"]) if p) or "sí"))
    if planta_g:
        filas.append(("Planta de respaldo", "Sí" + (f" ({_kva_txt(planta_g['kva'])} kVA)" if planta_g["kva"] is not None else "")
                      + (f" · transferencia {planta_g['transf_txt']}" if planta_g["transf"] else "")))
    filas.append(("Normativa", f"CREG 038/2014 · RETIE 2024 · Bornera {norma}"))

    filas_w = [(k, textwrap.wrap(v, 46) or [""]) for k, v in filas]
    cuadro_h = 8.0 + sum(2.7 + 2.0 * (len(ls) - 1) for _, ls in filas_w)
    W = 155
    # El cuadro va sobre el plano de simbologia (que termina en y=92): el
    # lienzo crece solo lo que haga falta (escala constante: la altura de la
    # figura crece en proporcion, asi el tamano de simbolos y texto no cambia).
    H = max(115, int(math.ceil(105 + cuadro_h)))

    fig, ax = plt.subplots(figsize=(16, 11 * H / 115))
    ax.set_xlim(0, W); ax.set_ylim(0, H)
    ax.set_aspect("equal"); ax.axis("off")

    # ── Título ────────────────────────────────────────────────────────────────
    ax.text(W/2, H-2, "DIAGRAMA UNIFILAR DE MEDIDA",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    circuito = str(cfg.get("circuito", "")).strip()
    if circuito:
        ax.text(W/2, H-3.6, f"Circuito: {circuito}",
                ha="center", fontsize=9.5, fontweight="bold", color="#444")
    sub_parts = [f"Medida {tipo_txt}", sis_short, f"Norma {norma}"]
    if rel_tc:  sub_parts.append(f"RTC {rel_tc}")
    if rel_tp:  sub_parts.append(f"RTP {rel_tp}")
    if respaldo: sub_parts.append("Principal + Respaldo")
    if es_multi_celda:
        sub_parts.append(f"Subestación · {n_trafos} celdas de transformación")
    if instalacion == "trafo" and trafo_uso == "compartido":
        sub_parts.append("Trafo COMPARTIDO (varios usuarios)")
    elif instalacion == "trafo" and trafo_uso == "exclusivo":
        sub_parts.append("Trafo exclusivo")
    cal = cfg.get("calibre_conductor") or cfg.get("calibre_acometida")
    if cal: sub_parts.append(f"Calibre {cal}")
    ax.text(W/2, H-5.5, "  ·  ".join(sub_parts),
            ha="center", fontsize=8.5, color="#666")

    # directa + PRINCIPAL/RESPALDO + trafo compartido en gabinete: el recinto abarca los dos medidores
    # (xc +- 25) y con xc=22 su borde izquierdo quedaba FUERA del lienzo (recortado): se corre el eje.
    caja_ancha = (bool(cfg.get("trafo_gabinete", False)) and respaldo and tipo == "directa"
                  and instalacion == "trafo" and trafo_uso == "compartido")
    xc = 22 + (6 if caja_ancha else 0)   # eje vertical principal
    y  = H - 11

    # ── Helpers ───────────────────────────────────────────────────────────────
    def vline(ya, yb, lw=2.6, ls="-"):
        ax.plot([xc, xc], [ya, yb], color=INK, lw=lw, zorder=2, ls=ls)

    def cable_lbl(ya, yb, lbl, lado=-1):
        ym = (ya + yb) / 2
        dx = 2.5 * lado
        ax.plot([xc+dx*0.4, xc+dx*1.1], [ym+0.6, ym-0.6], color="#555", lw=1.1, zorder=3)
        ax.text(xc+dx+1.5*lado, ym, lbl,
                ha="left" if lado > 0 else "right", va="center",
                fontsize=7.5, color="#444", style="italic")

    def node_dot(yy):
        ax.add_patch(Circle((xc, yy), 0.9, fc=INK, ec=INK, zorder=4))

    def busbar(yy, label, hw=14, lx=None):
        ax.plot([xc-hw, xc+hw], [yy, yy], color=INK, lw=5, zorder=2)
        ax.text(xc-16 if lx is None else lx, yy, label, ha="right", va="center",
                fontsize=9.5, fontweight="bold", color=INK)

    def secc_rotulo():
        """Rotulo del seccionador con su lado (MT/BT) -- calculado arriba
        (secc_lado); en MT incluye la tension de la red si se conoce."""
        tens = f" {v_mt_cfg}" if secc_lado == "MT" and v_mt_cfg else ""
        return f"Seccionador {secc_lado}{tens}\n(c/cuchilla a tierra)\n{secc_estado_txt}"

    def _secundario(rel):
        """'30/5' -> '5' (valor nominal del secundario); '' si no hay relacion
        legible. Acepta decimales ('13200/115.5')."""
        parte = str(rel or "").split("/")[-1].strip()
        return parte if "/" in str(rel or "") and re.fullmatch(r"\d+(?:[.,]\d+)?", parte) else ""

    def draw_prot(label, amp, polos=None, tipo=None):
        """Dibuja interruptor de proteccion en la posicion actual de y."""
        nonlocal y
        vline(y, y - 2)
        _u_breaker(ax, xc, y - 2, INK, 0.9)
        detalle_partes = [p for p in (amp, f"{polos}P" if polos else None, tipo) if p]
        detalle = "  ".join(detalle_partes)
        lbl = f"{label}\n{detalle}" if detalle else label
        ax.text(xc - 5, y - 2, lbl, ha="right", va="center",
                fontsize=8, color=INK, fontweight="bold")
        vline(y - 2, y - 5); y -= 5

    # ── draw_medida_lateral ───────────────────────────────────────────────────
    # TC y TP como ramas horizontales → BLOQUE DE PRUEBA → MEDIDOR
    def draw_medida_lateral(tc_y, tp_y=None):
        """
        tc_y  : nivel y donde el TC se ramifica hacia la derecha.
        tp_y  : nivel y donde el TP se ramifica (solo indirecta). Si es None, solo TC.
        Bloque y medidor quedan a la derecha del eje principal.
        """
        # Posiciones horizontales
        sym_x  = xc + 12    # centro símbolo TC / TP
        bq_x0  = xc + 20   # borde izquierdo bloque
        bq_w   = 19
        bq_x1  = bq_x0 + bq_w
        med_x0 = bq_x1 + 4
        med_w  = 21
        med_x1 = med_x0 + med_w

        # Centro vertical del conjunto bloque+medidor (proporciones ajustadas:
        # antes el bloque quedaba exagerado, mucho mas alto de lo que un
        # bloque de pruebas real necesita para verse).
        if tp_y is not None:
            bq_cy = (tp_y + tc_y) / 2
            bq_h  = abs(tp_y - tc_y) + (8 if not respaldo else 16)
        else:
            bq_cy = tc_y
            # Mas compacto que antes (era 12/22): con TC solo (semidirecta),
            # un bloque tan alto como el medidor los hacia ver como "gemelos"
            # del mismo tamano -- el bloque de pruebas real es mas chico y
            # discreto que el medidor, que es el elemento protagonico.
            bq_h  = 9 if not respaldo else 18

        # ── TC: EN SERIE con la linea (lleva la corriente hacia la medida) ───
        # Linea mas gruesa = tramo de corriente. Del TC sale el hilo que
        # llega al bloque/medidor (la medida de energia depende de esta
        # corriente); el TP solo aporta la referencia de tension.
        node_dot(tc_y)
        ax.plot([xc, sym_x - 1.8], [tc_y, tc_y], color=COL["R"], lw=2.1, zorder=3)
        _u_ct(ax, sym_x, tc_y, COL["R"], 1.0)
        ax.text(sym_x, tc_y - 3.3, f"TC {rel_tc or '---'}\n(serie)",
                ha="center", va="top", fontsize=7, color=COL["R"], fontweight="bold")
        # Rotulo del SECUNDARIO (lo que realmente llega al bloque/medidor):
        # 30/5 -> 5 A. Corto a proposito: solo hay ~6 unidades entre el
        # simbolo y el bloque.
        sec_tc = _secundario(rel_tc)
        if sec_tc:
            ax.text(bq_x0 - 0.7, tc_y + 0.9, f"sec. {sec_tc} A", ha="right", va="bottom",
                    fontsize=5.6, color=COL["R"], fontweight="bold")
        # hilo TC → entrada izquierda del bloque (a la altura bq_cy o tc_y)
        entry_tc_y = bq_cy + bq_h/2 - 3 if tp_y is not None else bq_cy
        ax.plot([sym_x + 1.8, bq_x0], [tc_y, tc_y], color=INK, lw=1.9, zorder=3)
        if abs(tc_y - entry_tc_y) > 0.5:
            ax.plot([bq_x0, bq_x0], [tc_y, entry_tc_y], color=INK, lw=1.9, zorder=3)

        # ── TP: EN PARALELO (solo tension de referencia, sin corriente) ──────
        # Linea mas delgada a proposito -- no es el mismo tipo de conexion
        # que el TC y no deberia verse igual de "gruesa"/prominente.
        if tp_y is not None:
            node_dot(tp_y)
            ax.plot([xc, sym_x - 1.8], [tp_y, tp_y], color=COL["S"], lw=1.1, zorder=3)
            # ground=True: el TP cierra su circuito de referencia a tierra
            # (antes quedaba sin cerrar, como un instrumento "flotando").
            _u_vt(ax, sym_x, tp_y, COL["S"], 0.9, ground=True)
            ax.text(sym_x, tp_y + 3.3, f"(paralelo)\nTP {rel_tp or '---'}",
                    ha="center", va="bottom", fontsize=7, color=COL["S"], fontweight="bold")
            sec_tp = _secundario(rel_tp)
            if sec_tp:
                ax.text(bq_x0 - 0.7, tp_y + 0.9, f"sec. {sec_tp} V", ha="right", va="bottom",
                        fontsize=5.6, color=COL["S"], fontweight="bold")
            entry_tp_y = bq_cy - bq_h/2 + 3
            ax.plot([sym_x + 1.8, bq_x0], [tp_y, tp_y], color=INK, lw=1.1, zorder=3)
            if abs(tp_y - entry_tp_y) > 0.5:
                ax.plot([bq_x0, bq_x0], [tp_y, entry_tp_y], color=INK, lw=1.1, zorder=3)

        # ── Fusible de medida (opcional) ─────────────────────────────────────
        if interruptor_medida:
            fx = (xc + bq_x0) / 2
            ax.plot([xc + 1.8, fx - 0.7], [tc_y, tc_y], color=INK, lw=1.6, zorder=4)
            _u_fuse(ax, fx, tc_y, INK, 0.5)
            ax.text(fx, tc_y + 1.6, "Fusible\nmedida", ha="center", va="bottom",
                    fontsize=6, color=INK, fontweight="bold", zorder=5)
            ax.plot([fx + 0.7, bq_x0], [tc_y, tc_y], color=INK, lw=1.6, zorder=4)

        # ── BLOQUE DE PRUEBA ──────────────────────────────────────────────────
        _u_bloque_prueba(ax, bq_x0, bq_cy - bq_h/2, bq_w, bq_h, "BLOQUE DE PRUEBA", norma)

        # ── Hilo bloque → medidor ────────────────────────────────────────────
        ax.plot([bq_x1, med_x0], [bq_cy, bq_cy], color=INK, lw=1.8, zorder=3)

        # ── MEDIDOR(ES) ───────────────────────────────────────────────────────
        # Radio FIJO (no derivado de bq_h) -- el medidor es el elemento
        # protagonico del diagrama, su tamano no deberia depender de cuanto
        # mida el bloque de pruebas (antes ambos quedaban casi identicos).
        if not respaldo:
            r = 8.0
            mcx = med_x0 + r + 1
            _u_meter(ax, mcx, bq_cy, r=r, label_below="MEDIDOR")
            med_span = (bq_cy - r, bq_cy + r)
        else:
            # PRINCIPAL + RESPALDO: dos medidores EN PARALELO desde el mismo
            # nodo (ambos miden la misma acometida, no en serie).
            r = 6.0
            mcx = med_x0 + r + 1
            sep = r * 2 + 3
            y_p, y_r = bq_cy + sep/2, bq_cy - sep/2
            jx = med_x0 - 1
            ax.plot([bq_x1, jx], [bq_cy, bq_cy], color=INK, lw=1.5, zorder=3)
            ax.plot([jx, jx], [y_p, y_r], color=INK, lw=1.5, zorder=3)
            for etq, my in [("PRINCIPAL", y_p), ("RESPALDO", y_r)]:
                ax.plot([jx, mcx - r], [my, my], color=INK, lw=1.4, zorder=3)
                _u_meter(ax, mcx, my, r=r, fontsize=6.8, lw=1.5, label_below=etq, label_fontsize=6)
            med_span = (y_r - r, y_p + r)

        # Si el trafo es compartido, señalar EXPLICITAMENTE el medidor (no el
        # trafo/barraje) como el punto que corresponde a este usuario -- ese
        # es justamente el dato que importa distinguir entre los N medidores
        # que cuelgan del mismo punto compartido.
        if es_compartido:
            ax.annotate("ESTE MEDIDOR", xy=(mcx, med_span[1]), xytext=(mcx, med_span[1] + 6),
                        ha="center", va="bottom", fontsize=7, color="#8a4b00", fontweight="bold",
                        arrowprops=dict(arrowstyle="-|>", color="#8a4b00", lw=1.3))
            if gabinete and bt_y is not None:
                # El gabinete/cuarto de medidores compartido encierra el
                # BARRAJE BT y LOS MEDIDORES (TC/bloque/medidor de este
                # usuario incluidos) -- NUNCA el transformador, que
                # fisicamente esta afuera (poste o camara propia).
                gx0 = xc - 15
                gx1 = mcx + r + 2
                gy1 = bt_y + 2
                gy0 = med_span[0] - 4          # (antes -2: el rotulo MEDIDOR/RESPALDO quedaba sobre el borde)
                ax.add_patch(FancyBboxPatch((gx0, gy0), gx1 - gx0, gy1 - gy0,
                             boxstyle="round,pad=0.4,rounding_size=1.5",
                             fill=False, ec="#8a4b00", lw=1.3, ls=(0, (4, 2)), zorder=1))
                # encima del borde superior derecho: a la derecha del recinto invadia el cuadro de datos
                ax.text(gx1, gy1 + 1.0, "GABINETE\nCOMPARTIDO", ha="right", va="bottom",
                        fontsize=6.3, color="#8a4b00", fontweight="bold")

    # ── FUENTE / ENTRADA ──────────────────────────────────────────────────────
    if tipo == "indirecta":
        v_mt = cfg.get("v_mt", "M.T.")
        ax.text(xc, y+1, f"RED ({v_mt})", ha="center", va="bottom",
                fontsize=9.5, fontweight="bold", color=INK)
        ls_acometida = (0, (1.5, 1.2)) if cfg.get("tendido") == "subterraneo" else "-"
        vline(y+1, y, ls=ls_acometida)
        if cfg.get("tendido") == "subterraneo":
            cable_lbl(y+1, y, "subterráneo", lado=-1)
        # Pararrayos ZnO lateral (RETIE 2024). NOTA: aqui el espacio entre el
        # eje y el bloque TC/TP (bq_x0 = xc+20, ver draw_medida_lateral) es
        # muy angosto -- a diferencia del bloque TRAFO de directa/semidirecta,
        # NO hay espacio para dibujar un banco de N iconos sin encimarse con
        # el TC/TP/bloque. Se dibuja siempre UN solo icono y se anota la
        # cantidad en el texto si el usuario especifico mas de uno.
        dps_n = max(1, int(cfg.get("dps_cantidad", 1)))
        arrx = xc + 18
        ax.plot([xc, arrx], [y, y], color=COL["G"], lw=1.5, zorder=3)
        _u_arrester(ax, arrx, y - 3, COL["G"], 0.82)
        dps_lbl = "Pararrayos ZnO" if dps_n == 1 else f"Pararrayos ZnO (banco de {dps_n})"
        ax.text(arrx + 3, y - 1.5, dps_lbl,
                ha="left", va="center", fontsize=7.5, color=COL["G"], fontweight="bold")
        vline(y, y - 3); y -= 3
        # NOTA: no se dibuja un "seccionador MT" aparte aqui -- los CC
        # fusibles de abajo YA cumplen esa funcion (se pueden abrir en vacio
        # para seccionar, ademas de proteger); poner ambos es redundante e
        # incoherente (dos elementos de corte en serie sin proposito real).
    elif instalacion == "barraje":
        ten_bt = cfg.get("tension_bt", "")
        bar_lbl = f"BARRAJE {ten_bt} V" if ten_bt else "BARRAJE B.T."
        busbar(y, bar_lbl)
        vline(y, y - 4); y -= 4
    elif instalacion == "trafo":
        # la RED MT es una derivacion de un alimentador/anillo que sigue
        # sirviendo otros puntos, no una acometida exclusiva en punta de
        # linea -- se marca con una linea horizontal corta (tipo "T") para
        # diferenciarla.
        mt_y = y + 1
        ax.plot([xc - 9, xc + 9], [mt_y, mt_y], color=INK, lw=2.2, zorder=2)
        v_mt_lbl = cfg.get("v_mt", "") or "M.T."
        ax.text(xc, mt_y + 1.3, f"RED ({v_mt_lbl})", ha="center", va="bottom",
                fontsize=9.5, fontweight="bold", color=INK)
        ls_acometida = (0, (1.5, 1.2)) if cfg.get("tendido") == "subterraneo" else "-"
        vline(mt_y, y - 4, ls=ls_acometida); y -= 4
        if cfg.get("tendido") == "subterraneo":
            cable_lbl(mt_y, y, "subterráneo", lado=-1)
    else:
        # Sin trafo ni barraje explicito: acometida directa desde la red BT
        # (caso mas simple, ej. residencial). Solo el rotulo, sin simbolo de
        # barra -- no hay ningun elemento fisico de conmutacion/derivacion
        # que representar aqui.
        ax.text(xc, y + 1, "RED (B.T.)", ha="center", va="bottom",
                fontsize=9.5, fontweight="bold", color=INK)
        vline(y + 1, y - 4); y -= 4

    # ── INDIRECTA: punto de medida MT (TC + TP → bloque lateral) ──────────────
    if tipo == "indirecta":
        # Cortacircuitos fusibles MT de protección de TPs
        n_cc = int(cfg.get("n_cc", 3))
        cc_y = y - 3
        vline(y, cc_y)
        if n_cc >= 3:
            for dx in [-2.5, 0, 2.5]:
                _u_fuse(ax, xc + dx, cc_y, INK, 0.72)
            cc_lbl = f"{n_cc} CC fusibles MT"
        elif n_cc == 2:
            for dx in [-1.5, 1.5]:
                _u_fuse(ax, xc + dx, cc_y, INK, 0.75)
            cc_lbl = "2 CC fusibles MT"
        else:
            _u_fuse(ax, xc, cc_y, INK, 0.85)
            cc_lbl = "CC fusible MT"
        ax.text(xc - 5, cc_y, cc_lbl, ha="right", va="center",
                fontsize=7.5, color=INK, fontweight="bold")
        # 6 (no 3): el rotulo "(paralelo) TP ..." del TP (arriba del simbolo)
        # llega hasta el pararrayos lateral de arriba (arrx = xc+18) si el TP
        # queda mas cerca -- se encimaban el texto y la tierra del pararrayos.
        vline(cc_y, cc_y - 6); y = cc_y - 6

        # TC + TP como ramas horizontales (tp arriba, tc abajo del nodo)
        tp_y = y
        tc_y = y - 6
        vline(tp_y, tc_y)
        draw_medida_lateral(tc_y, tp_y=tp_y)
        # Conductor desde el nodo del TC hasta lo que sigue (seccionador / trafo /
        # barra de distribucion). Faltaba: dejaba ~3 u de circuito abierto bajo el
        # TC (semidirecta si lo dibuja: vline(tc_y, tc_y - 5)).
        vline(tc_y, tc_y - 3)
        y = tc_y - 3

    # ── SUBESTACION MULTI-CELDA: N transformadores INDEPENDIENTES, cada uno ───
    # con su propia proteccion y su propia carga, colgando de una barra de
    # distribucion comun despues del punto de medida MT. Reemplaza el banco de
    # monofasicos en paralelo cuando hay 2+ trafos en indirecta.
    if es_multi_celda:
        kva_list = cfg.get("trafo_kva_list", [])
        # Ancho total del abanico acotado: con muchas celdas, una barra muy
        # ancha llega a rozar la etiqueta "MEDIDOR" (que vive a la derecha,
        # ~x=75, casi al mismo nivel vertical que esta barra).
        cell_w = max(5.0, min(11.0, 35.0 / max(1, n_trafos - 1)))
        xs = [xc + i * cell_w for i in range(n_trafos)]
        bus_y = y - 4
        vline(y, bus_y)  # el feed de medida baja por el eje hasta la barra
        ax.plot([xc - 3, xs[-1] + 3], [bus_y, bus_y], color=INK, lw=4.5, zorder=2)
        ax.text(xc - 5, bus_y + 2.2, "BARRA DE\nDISTRIBUCIÓN", ha="right", va="bottom",
                fontsize=6.8, fontweight="bold", color=INK)

        for i, cx in enumerate(xs):
            kva_i = kva_list[i] if i < len(kva_list) else kva
            # Celdas muy juntas (cell_w < 8): "500 kVA" en una linea mide ~6.5 u
            # y pisa el rotulo de la celda vecina -> tres lineas cortas.
            if kva_i and cell_w < 8:
                lbl = f"TR{i+1}\n{kva_i}\nkVA"
            else:
                lbl = f"TR{i+1}\n{kva_i} kVA" if kva_i else f"TR{i+1}"
            # Etiqueta a la DERECHA de la rama (centrada quedaba tachada por la
            # linea de la rama). Ancho ~3.5 u + 0.9 de margen < cell_w minimo
            # (5 u), asi que no llega a la celda vecina -- verificado con 8.
            ax.text(cx + 0.9, bus_y - 1.2, lbl, ha="left", va="top",
                    fontsize=6.2, fontweight="bold", color=INK)
            fy = bus_y - 6.5
            ax.plot([cx, cx], [bus_y, fy + 2.2], color=INK, lw=1.6, zorder=3)
            _u_fuse(ax, cx, fy, INK, 0.62)
            ty = fy - 2.2 - 5.5
            ax.plot([cx, cx], [fy - 2.2, ty + 2.5], color=INK, lw=1.6, zorder=3)
            _u_xfmr(ax, cx, ty, INK, 0.9, ground=False)
            # tierra en ramal lateral, igual criterio que el trafo principal:
            # no se dibuja sobre el eje del cable para que no quede tapada.
            gnd_y = ty - 1.5 * 0.9
            ax.plot([cx, cx + 2.3], [gnd_y, gnd_y], color=COL["G"], lw=1.0, zorder=3)
            _ground(ax, cx + 2.3, gnd_y, 0.35)
            ly0 = ty - 2.5 - 3.5
            ax.plot([cx, cx], [ty - 2.5, ly0], color=INK, lw=1.6, zorder=3)
            ax.add_patch(Polygon([[cx - 2.2, ly0], [cx + 2.2, ly0], [cx, ly0 - 4]],
                         closed=True, fill=False, ec=INK, lw=1.6, zorder=3))
            ax.text(cx, ly0 - 5.3, "CARGA", ha="center", va="top",
                    fontsize=6, fontweight="bold", color=INK)

    # ── TRAFO (instalacion=trafo) ──────────────────────────────────────────────
    if instalacion == "trafo" and not es_multi_celda:
        # Proteccion MT del trafo (RETIE): en indirecta el punto de medida ya
        # se protegio arriba (CC fusibles del TC/TP); en directa/semidirecta
        # el trafo cuelga directo de "RED (M.T.)" y esta es su PRIMERA
        # proteccion, por eso se dibuja siempre (pararrayos + cortacircuitos).
        if tipo != "indirecta":
            dps_n = max(1, int(cfg.get("dps_cantidad", 1)))
            arrx = xc + 12
            ax.plot([xc, arrx], [y, y], color=COL["G"], lw=1.3, zorder=3)
            xs_dps = [arrx + (i - (dps_n-1)/2) * 2.4 for i in range(dps_n)]
            for ax_x in xs_dps:
                _u_arrester(ax, ax_x, y - 3, COL["G"], 0.72 if dps_n == 1 else 0.55)
            dps_lbl = "Pararrayos ZnO" if dps_n == 1 else f"Pararrayos ZnO (banco de {dps_n})"
            ax.text(max(xs_dps) + 2.5, y - 1.5, dps_lbl,
                    ha="left", va="center", fontsize=6.8, color=COL["G"], fontweight="bold")
            vline(y, y - 3); y -= 3
            _u_fuse(ax, xc, y - 2, INK, 0.78)
            ax.text(xc - 5, y - 2, "Cortacircuitos\nMT", ha="right", va="center",
                    fontsize=7, color=INK, fontweight="bold")
            vline(y - 2, y - 4); y -= 4

        if seccionador_pos == "antes":
            # La linea llega SOLO hasta el contacto superior (y_c+2) y sale
            # desde el inferior (y_c-2): si atravesara el simbolo, el
            # seccionador (abierto) se leeria como puenteado/cerrado.
            vline(y, y - 1)
            _u_disc(ax, xc, y - 3, INK, 1.0, tierra=True)
            if not secc_abierto:
                vline(y - 1, y - 5)      # cerrado: el conductor pasa por el seccionador
            ax.text(xc - 5, y - 3, secc_rotulo(), ha="right", va="center",
                    fontsize=7.2, color=INK, fontweight="bold")
            # 7 (no 5): el contacto inferior del seccionador queda en y-5 y el
            # circulo superior del trafo llega hasta ~y-5.4 -- con 5 el
            # contacto quedaba DENTRO del circulo del trafo.
            vline(y - 5, y - 7); y -= 7

        trafo_y = y - 5
        kva_list = cfg.get("trafo_kva_list", [])

        def _banco_lbl(n_t):
            if kva_list and len(kva_list) == n_t:
                return (f"{n_t} x {kva_list[0]} kVA" if len(set(kva_list)) == 1
                        else " + ".join(kva_list) + " kVA")
            return f"{n_t} x {kva} kVA" if kva else ""

        if n_trafos >= 2:
            spacing = min(3.0, 12.0 / n_trafos)
            xs = [(i - (n_trafos-1)/2) * spacing * 2 for i in range(n_trafos)]
            for dx in xs:
                ax.add_patch(Circle((xc+dx, trafo_y+2.2), 2.0, fill=False, ec=INK, lw=1.6))
                ax.add_patch(Circle((xc+dx, trafo_y-2.2), 2.0, fill=False, ec=INK, lw=1.6))
                # tierra en ramal lateral (no tapada por la linea principal)
                ax.plot([xc+dx, xc+dx+2.2], [trafo_y-2.2, trafo_y-2.2], color=COL["G"], lw=1.1, zorder=3)
                _ground(ax, xc+dx+2.2, trafo_y-2.2, 0.32)
            trafo_lbl = f"Trafo\n{_banco_lbl(n_trafos)}" if _banco_lbl(n_trafos) else "Trafo"
        else:
            _u_xfmr(ax, xc, trafo_y, INK, 1.25, ground=False)
            # Tierra del neutro secundario en ramal lateral: si se dibujara
            # sobre el eje (xc) la tapa la linea principal que sigue derecho
            # hacia el medidor (ver _u_xfmr, que la dibuja en (xc, y) por
            # defecto). Se saca a un lado para que quede siempre visible.
            gnd_y = trafo_y - 1.5 * 1.25
            ax.plot([xc, xc + 3.5], [gnd_y, gnd_y], color=COL["G"], lw=1.3, zorder=3)
            _ground(ax, xc + 3.5, gnd_y, 0.5)
            trafo_lbl = f"Trafo {trafo_tipo}\n{kva} kVA" if kva else f"Trafo {trafo_tipo}"

        # Dyn11 depende del TRANSFORMADOR (trifasico), no de la medida: un trafo trifasico puede alimentar
        # un medidor mono o bifasico. Sin fase de trafo dicha se sigue el sistema de la medida.
        _tt = str(trafo_tipo or "").lower()
        if _tt.startswith("tri") or (not _tt and sistema in ("tri3h", "tri4h")):
            trafo_lbl += "\nDyn11"
        ax.text(xc - 8, trafo_y, trafo_lbl,
                ha="right", va="center", fontsize=8.5, color=INK, fontweight="bold")
        # y = trafo_y - 5 (no -6): la linea llega hasta trafo_y-5 y lo que sigue
        # arranca en y; con -6 quedaba un hueco de 1 unidad (circuito abierto).
        vline(y, trafo_y - 5); y = trafo_y - 5

        if es_compartido:
            # El secundario del trafo alimenta un barraje BT del que se
            # derivan VARIOS medidores (cada uno con el suyo, tipicamente
            # directo). Este diagrama sigue UNO solo de esos derivados; el
            # resto se indica de forma esquematica, SIN invadir el espacio
            # donde mas abajo se dibuja la conexion propia de este usuario
            # (TC/bloque/medidor pueden ocupar bastante ancho a la derecha).
            # 9 (no 5): el circulo inferior del trafo llega a trafo_y-4.6; con el
            # barraje a -5 el recinto del gabinete (borde superior en bt_y+2)
            # CRUZABA el trafo, contra lo documentado (el trafo va siempre por
            # ENCIMA del borde superior del recinto, fuera de la caja).
            bt_y = trafo_y - 9
            vline(y, bt_y)
            n_us = str(cfg.get("trafo_n_usuarios", "") or "").strip()
            gabinete = bool(cfg.get("trafo_gabinete", False))
            lbl_otros = f"+ {n_us} medidores mas\nen este punto" if n_us else "+ otros medidores\nen este punto"
            if not gabinete:
                lbl_otros += "\n(red abierta)"

            # NOTA: el recinto de "gabinete compartido" (si aplica) se dibuja
            # MAS ABAJO, despues del medidor -- el gabinete de medidores
            # encierra el barraje + los medidores, NUNCA el transformador
            # (que fisicamente esta afuera: en su propio poste o camara).
            # directa + PRINCIPAL/RESPALDO + gabinete: el recinto debe abarcar los DOS medidores
            # (xc +- 25): la barra se ensancha con el y los rotulos quedan FUERA del recinto.
            busbar(bt_y, "BARRAJE BT\n(COMPARTIDO)", hw=(24 if caja_ancha else 14),
                   lx=(xc - 27 if caja_ancha else None))
            # TODA nota del punto compartido va del lado IZQUIERDO: el
            # derecho lo ocupa, mas abajo, la conexion de este usuario
            # (TC/bloque/medidor), y ese bloque puede crecer bastante si
            # hay respaldo -- un texto a la derecha terminaria tapado por
            # esa caja opaca (bug real ya visto: "(red abierta)" quedaba
            # oculto detras del BLOQUE DE PRUEBA cuando habia respaldo).
            # con gabinete el recinto llega a xc-15,4: el rotulo debe quedar FUERA (antes lo cruzaba)
            ax.text(xc - (27 if caja_ancha else 17.5 if gabinete else 14),
                    bt_y - 2.8, lbl_otros, ha="right", va="top",
                    fontsize=6.8, color="#8a4b00", style="italic", fontweight="bold")

            # Espacio explicito antes de la conexion propia de ESTE usuario,
            # para que TC/bloque/medidor -- y su etiqueta "ESTE MEDIDOR" --
            # nunca se crucen con el barraje ni con "(red abierta)".
            cable_lbl(bt_y - 2, bt_y - 6, calibre or "cal. ?", lado=-1)
            # y = bt_y - 7 (no -8): con -8 quedaba un hueco de 1 u entre este
            # tramo y lo que sigue (derivacion a los medidores / proteccion).
            vline(bt_y, bt_y - 7); y = bt_y - 7
        else:
            # El rotulo del conductor necesita su PROPIO tramo de linea, sin
            # nada pegado: con solo ~0.6 u entre el trafo y la proteccion /
            # seccionador siguiente, "cal. ?" tocaba el circulo inferior del
            # trafo y, con proteccion despues, quedaba ENCIMA de su rotulo.
            cable_lbl(y, y - 5, calibre or "cal. ?", lado=-1)
            vline(y, y - 5); y -= 5

    # ── SEMIDIRECTA: TC como rama horizontal → bloque + medidor ───────────────
    if tipo == "semidirecta":
        tc_y = y
        # Conductor solo si NO viene de trafo (si viene de trafo ya se
        # etiqueto arriba, en el bloque TRAFO); aplica tanto a "barraje"
        # como al caso sin instalacion especificada.
        if instalacion != "trafo":
            cable_lbl(y + 3, y, calibre or "cal. ?", lado=-1)
        draw_medida_lateral(tc_y)
        vline(tc_y, tc_y - 5); y = tc_y - 5
        # Proteccion ANTES del medidor (si aplica)
        if prot_antes:
            draw_prot("Proteccion", prot_antes, polos=cfg.get("interruptor_polos"), tipo=cfg.get("interruptor_tipo"))

    # ── DIRECTA: medidor en linea, sin bloque de prueba ───────────────────────
    if tipo == "directa":
        # Si viene de trafo, el conductor ya se etiqueto al final del bloque
        # TRAFO; para "barraje" y para sin instalacion especificada aun no.
        if instalacion != "trafo":
            cable_lbl(y + 3, y - 1, calibre or "cal. ?", lado=-1)
        # Proteccion ANTES del medidor
        if prot_antes:
            draw_prot("Proteccion", prot_antes, polos=cfg.get("interruptor_polos"), tipo=cfg.get("interruptor_tipo"))
        # Medidor en linea -- simbolo normalizado: circulo con "kWh"
        # (igual convencion que el resto del diagrama, sin cajas oscuras).
        # El medidor arranca 2 u debajo de y (antes y_mid = y-5 con r=6.5 lo
        # subia 1.5 u POR ENCIMA de y: se encimaba con la proteccion/linea de
        # arriba y vline(y, y_mid+r) dibujaba hacia arriba).
        r = 6.5
        y_mid = y - 2 - r
        if not respaldo:
            vline(y, y_mid + r)
            # rotulo a la derecha de la linea (la linea sigue hacia abajo)
            _u_meter(ax, xc, y_mid, r=r, lw=1.7, label_below="MEDIDOR",
                     label_dx=1.2, label_ha="left")
            if es_compartido:
                ax.annotate("ESTE MEDIDOR", xy=(xc + r, y_mid),
                            xytext=(xc + (17.5 if gabinete else r + 8), y_mid),
                            ha="left", va="center", fontsize=7, color="#8a4b00", fontweight="bold",
                            arrowprops=dict(arrowstyle="-|>", color="#8a4b00", lw=1.3))
                if gabinete and bt_y is not None:
                    # Encierra barraje BT + medidor -- NUNCA el trafo (queda
                    # arriba de bt_y, fuera del recinto).
                    gx0, gx1 = xc - 15, xc + 15
                    gy1, gy0 = bt_y + 2, y_mid - r - 4
                    ax.add_patch(FancyBboxPatch((gx0, gy0), gx1 - gx0, gy1 - gy0,
                                 boxstyle="round,pad=0.4,rounding_size=1.5",
                                 fill=False, ec="#8a4b00", lw=1.3, ls=(0, (4, 2)), zorder=1))
                    ax.text(gx1 + 1, gy1 - 0.5, "GABINETE\nCOMPARTIDO", ha="left", va="top",
                            fontsize=6.3, color="#8a4b00", fontweight="bold")
            # 5 u de conductor bajo el circulo (antes `y - 12` con el medidor
            # 3.5 u mas arriba): da espacio al rotulo "MEDIDOR" y deja la CARGA
            # separada del medidor.
            vline(y_mid - r, y_mid - r - 5)
            y = y_mid - r - 5
        else:
            # PRINCIPAL + RESPALDO (chequeo): dos medidores EN PARALELO desde
            # el mismo nodo de derivacion -- ambos miden la misma acometida,
            # NUNCA en serie (uno no depende del otro para dejar pasar la
            # corriente). Antes esto se dibujaba como UN solo medidor pese a
            # que el subtitulo ya decia "Principal + Respaldo": discrepancia
            # real entre el texto y el dibujo.
            r = 5.5
            jy = y - 2                 # nodo de derivacion: justo debajo de y
            y_mid = jy - 2.5 - r
            dxs = (-(r + 9), (r + 9))
            vline(y, jy)
            ax.plot([xc + dxs[0], xc + dxs[1]], [jy, jy], color=INK, lw=1.8, zorder=3)
            # 5 (no 2.5): los rotulos PRINCIPAL/RESPALDO quedaban tachados por
            # la barra horizontal de union; ademas van a cada lado de su
            # conductor vertical, no encima.
            out_y = y_mid - r - 5
            for dx, etq in [(dxs[0], "PRINCIPAL"), (dxs[1], "RESPALDO")]:
                cx = xc + dx
                ax.plot([cx, cx], [jy, y_mid + r], color=INK, lw=1.5, zorder=3)
                _u_meter(ax, cx, y_mid, r=r, fontsize=7, lw=1.6, label_below=etq, label_fontsize=6,
                         label_dx=(-1.0 if dx < 0 else 1.0), label_ha=("right" if dx < 0 else "left"))
                ax.plot([cx, cx], [y_mid - r, out_y], color=INK, lw=1.5, zorder=3)
            if es_compartido:
                # Apunta al PUNTO (principal+respaldo juntos), no a un
                # medidor especifico -- ambos son "este" punto de medida.
                # Se señala desde la derecha (space libre) para no invadir
                # el area del trafo/barraje/gabinete que queda arriba.
                ax.annotate("ESTE MEDIDOR", xy=(xc + dxs[1] + r, y_mid),
                            xytext=(xc + dxs[1] + r + 8, y_mid),
                            ha="left", va="center", fontsize=7, color="#8a4b00", fontweight="bold",
                            arrowprops=dict(arrowstyle="-|>", color="#8a4b00", lw=1.3))
                if gabinete and bt_y is not None:
                    # Encierra barraje BT + ambos medidores -- NUNCA el trafo.
                    gx0, gx1 = xc - 25, xc + 25            # (antes dxs +- 3: cortaba los circulos de los medidores)
                    gy1, gy0 = bt_y + 2, out_y - 2
                    ax.add_patch(FancyBboxPatch((gx0, gy0), gx1 - gx0, gy1 - gy0,
                                 boxstyle="round,pad=0.4,rounding_size=1.5",
                                 fill=False, ec="#8a4b00", lw=1.3, ls=(0, (4, 2)), zorder=1))
                    ax.text(gx1 + 1, gy1 - 0.5, "GABINETE\nCOMPARTIDO", ha="left", va="top",
                            fontsize=6.3, color="#8a4b00", fontweight="bold")
            ax.plot([xc + dxs[0], xc + dxs[1]], [out_y, out_y], color=INK, lw=1.8, zorder=3)
            vline(out_y, out_y - 8); y = out_y - 8

    # ── Proteccion DESPUES del medidor ────────────────────────────────────────
    if prot_despues and not es_multi_celda:
        draw_prot("Proteccion", prot_despues, polos=cfg.get("interruptor_polos"), tipo=cfg.get("interruptor_tipo"))

    # ── Seccionador DESPUES de la medida (si aplica) ──────────────────────────
    if es_multi_celda:
        pass  # cada celda ya tiene su propia proteccion + carga (ver arriba)
    elif seccionador_pos == "despues":
        vline(y, y - 1)   # solo hasta el contacto superior (ver nota arriba)
        _u_disc(ax, xc, y - 3, INK, 1.0, tierra=True)
        if not secc_abierto:
            vline(y - 1, y - 5)          # cerrado: el conductor pasa por el seccionador
        ax.text(xc - 5, y - 3, secc_rotulo(), ha="right", va="center",
                fontsize=7.2, color=INK, fontweight="bold")
        # 8 (no 5): con 5 el contacto inferior (y-5) quedaba exactamente
        # sobre el borde superior del triangulo de CARGA, tocandose.
        vline(y - 5, y - 8); y -= 8
    else:
        vline(y, y - 4); y -= 4

    # ── CARGA ─────────────────────────────────────────────────────────────────
    # (omitida en multi-celda: cada TRi ya dibujo su propia carga arriba)
    if not es_multi_celda:
        ax.add_patch(Polygon([[xc-5, y], [xc+5, y], [xc, y-9]],
                     closed=True, fill=False, ec=INK, lw=2.4))
        # Si es indirecta+trafo, el conductor trafo->carga ya se etiqueto al
        # final del bloque TRAFO (aqui no hay nada mas en medio que lo separe);
        # repetirlo seria la misma etiqueta dos veces sobre el mismo tramo.
        if not (tipo == "indirecta" and instalacion == "trafo"):
            ax.text(xc - 6.5, y - 3, calibre or "cal. ?", ha="right", va="center",
                    fontsize=7.5, color="#444", style="italic")
        ax.text(xc, y - 11, "CARGA",
                ha="center", va="top", fontsize=11, fontweight="bold", color=INK)
        if planta_g:     # del lado carga, despues de la proteccion y de la medida: nodo sobre el conductor
            _planta_simbolo(ax, xc, y + 3.2, planta_g, 6.5, +1, 0.85, med="el medidor")

    # ── CUADRO DE DATOS (panel derecho, sobre el plano de simbologia) ─────────
    # Resume lo dibujado (filas armadas arriba, antes de crear la figura).
    cx0, cx1 = 88, 152
    c_top = H - 9
    c_bot = c_top - cuadro_h
    ax.add_patch(FancyBboxPatch((cx0, c_bot), cx1 - cx0, cuadro_h,
                 boxstyle="round,pad=0.6,rounding_size=2",
                 fill=True, fc="#FAFAFA", ec="#2B2B2B", lw=1.5))
    ax.text((cx0 + cx1) / 2, c_top - 3, "CUADRO DE DATOS",
            ha="center", fontsize=10, fontweight="bold", color=INK)
    fy = c_top - 8.0
    for etq, lineas in filas_w:
        ax.text(cx0 + 2.5, fy, etq, ha="left", va="center",
                fontsize=7.2, fontweight="bold", color="#555")
        for j, ln in enumerate(lineas):
            ax.text(cx0 + 19, fy - 2.0 * j, ln, ha="left", va="center",
                    fontsize=7.5, color=INK)
        fy -= 2.7 + 2.0 * (len(lineas) - 1)

    # ── PLANO DE SIMBOLOGIA (panel derecho) ───────────────────────────────────
    px0, px1 = 88, 152
    py0, py1 = 4, 92
    ax.add_patch(FancyBboxPatch((px0, py0), px1-px0, py1-py0,
                 boxstyle="round,pad=0.6,rounding_size=2",
                 fill=True, fc="#FAFAFA", ec="#2B2B2B", lw=1.5))
    ax.text((px0+px1)/2, py1 - 3, "PLANO DE SIMBOLOGIA",
            ha="center", fontsize=10, fontweight="bold", color=INK)
    ax.text((px0+px1)/2, py1 - 6.5, "IEC / UNE 60617",
            ha="center", fontsize=7.5, color="#888", style="italic")

    sym_items = [
        ("Transformador de potencia (Dyn11)", lambda x,y: _u_xfmr(ax,x,y,INK,0.72)),
        ("Transformador de corriente (TC)",   lambda x,y: _u_ct(ax,x,y,COL["R"],0.82)),
        ("Transformador de tension (TP)",     lambda x,y: _u_vt(ax,x,y,COL["S"],0.82,True)),
        ("Cortacircuitos fusible MT",         lambda x,y: _u_fuse(ax,x,y,INK,0.82)),
        ("Interruptor automatico",            lambda x,y: _u_breaker(ax,x,y,INK,0.82)),
        ("Seccionador (c/cuchilla a tierra)", lambda x,y: _u_disc(ax,x,y,INK,0.82,tierra=True)),
        ("Pararrayos / DPS (ZnO)",            lambda x,y: _u_arrester(ax,x,y,COL["G"],0.72)),
        # Bloque de prueba y medidor: MISMAS funciones que dibujan el
        # simbolo real en el cuerpo del diagrama (_u_bloque_prueba/_u_meter)
        # -- antes este panel tenia iconos viejos (caja azul redondeada,
        # caja oscura solida) que ya no coincidian con lo que se dibujaba
        # arriba, exactamente el tipo de inconsistencia que hace que un
        # plano se vea poco profesional.
        ("Bloque de prueba",                  lambda x,y: _u_bloque_prueba(ax, x-3.5, y-2, 7, 4)),
        ("Medidor de energia (kWh)",          lambda x,y: _u_meter(ax, x, y, r=2.3, fontsize=4.2, lw=1.1)),
        ("Barra / barraje",                   lambda x,y: ax.plot(
            [x-3.5,x+3.5],[y,y],color=INK,lw=3.5)),
        ("Carga (general)",                   lambda x,y: ax.add_patch(
            Polygon([[x-2,y+2],[x+2,y+2],[x,y-2]],closed=True,fill=False,ec=INK,lw=1.6))),
    ]
    sx = px0 + 9; tx = px0 + 18
    item_ys = np.linspace(py1 - 12, py0 + 6, len(sym_items))
    for (lbl, draw_sym), yy in zip(sym_items, item_ys):
        draw_sym(sx, yy)
        ax.text(tx, yy, lbl, ha="left", va="center", fontsize=8, color=INK)

    plt.savefig(out_path, dpi=160, bbox_inches="tight",
                facecolor="white", pad_inches=0.3)
    plt.close(fig)
    return out_path

# ============================================================
#  DIAGRAMA UNIFILAR — TABLERO GENERAL BT (acometida/trafo + ramales)
# ============================================================
def draw_unifilar_tablero(cfg, out_path):
    """
    Unifilar de un tablero general de baja tension: acometida con proteccion
    primaria y transformador, interruptor principal, barra general y ramales
    de salida (proteccion + medicion + conductor + carga), estilo tecnico con
    cuadros de carga en slate (#0F172A) y tabla de convenciones.

    cfg:
      proyecto, circuito_entrada : str
      proteccion_primaria : str (texto libre; si contiene "seccion" dibuja
                            seccionador, de lo contrario fusible)
      trafo_kva, trafo_serie : str
      interruptor_principal : str (ej. '3x600 A')
      bus_voltaje : str (ej. '220/127 V')
      ramales: list[{
        proteccion : str opcional (ej. '3x400 A')
        medicion   : str opcional (ej. 'TC 400/5 A + CEM')
        medidor    : str opcional (ej. 'kWh') — medicion directa sin TC
        conductor  : str opcional (ej. '3 N.2/0')
        carga      : str — nombre de la carga
      }]
    """
    SLATE, SLATE_ED = "#0F172A", "#334155"

    ramales = cfg.get("ramales") or [{"carga": "Carga 1"}]
    n = len(ramales)
    branch_w = 24
    legend_w = 34
    content_w = max(branch_w, n * branch_w)
    W = legend_w + content_w + 12
    H = 118
    xm = legend_w + content_w / 2

    fig, ax = plt.subplots(figsize=(W / 9.0, H / 9.0))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    # ---------- titulo ----------
    y = H - 4
    ax.text(xm, y, cfg.get("proyecto") or "DIAGRAMA UNIFILAR — TABLERO GENERAL",
            ha="center", fontsize=13.5, fontweight="bold", color=INK)
    y -= 5.5
    circuito = cfg.get("circuito_entrada")
    if circuito:
        ax.text(xm, y, f"Circuito de entrada: {circuito}", ha="center", fontsize=9, color="#555555")
        y -= 6
    else:
        y -= 2

    # ---------- tronco de acometida (proteccion -> trafo -> interruptor ppal) ----------
    y_prot, y_xfmr, y_break = y - 6, y - 16, y - 26
    y_bus = y_break - 8
    ax.plot([xm, xm], [y, y_bus], color=INK, lw=2.2, zorder=2)

    prot_txt = cfg.get("proteccion_primaria", "")
    if "seccion" in prot_txt.lower():
        _u_disc(ax, xm, y_prot, INK, 1.1)
    else:
        _u_fuse(ax, xm, y_prot, INK, 1.1)
    ax.text(xm + 5, y_prot, prot_txt or "Proteccion primaria", ha="left", va="center",
            fontsize=8.3, color=INK, fontweight="bold")

    _u_xfmr(ax, xm, y_xfmr, INK, 1.15, ground=True)
    kva, serie = cfg.get("trafo_kva"), cfg.get("trafo_serie")
    tlabel = "TRAFO" + (f" {kva} kVA" if kva else "") + (f" · {serie}" if serie else "")
    ax.text(xm + 6.5, y_xfmr, tlabel, ha="left", va="center",
            fontsize=8.3, color=INK, fontweight="bold")

    _u_breaker(ax, xm, y_break, INK, 1.15)
    interr = cfg.get("interruptor_principal", "")
    ax.text(xm + 5, y_break, ("Interruptor ppal. " + interr).strip(), ha="left", va="center",
            fontsize=8.3, color=INK, fontweight="bold")

    # ---------- barra general ----------
    xs = [legend_w + branch_w / 2 + i * branch_w for i in range(n)]
    bx0, bx1 = min(xs) - 6, max(xs) + 6
    ax.plot([bx0, bx1], [y_bus, y_bus], color=INK, lw=4.2, zorder=3, solid_capstyle="butt")
    volt = cfg.get("bus_voltaje", "")
    ax.text(xm, y_bus + 2.4, ("BARRA GENERAL " + volt).strip(), ha="center", va="bottom",
            fontsize=9, fontweight="bold", color=INK)

    # ---------- ramales de salida ----------
    y_load = 20
    for x, ram in zip(xs, ramales):
        yy = y_bus - 2
        ax.plot([x, x], [y_bus, yy], color=INK, lw=1.8, zorder=2)

        prot = ram.get("proteccion")
        if prot:
            yy -= 4
            _u_breaker(ax, x, yy, INK, 0.85)
            ax.text(x, yy - 3.3, prot, ha="center", va="top", fontsize=6.6, color=INK)
            yy -= 4.5

        med, medidor = ram.get("medicion"), ram.get("medidor")
        if med:
            yy -= 3.5
            _u_ct(ax, x, yy, COL["R"], 0.8)
            ax.text(x, yy - 3.0, med, ha="center", va="top", fontsize=6.4, color=COL["R"])
            yy -= 4.2
        elif medidor:
            yy -= 4.5
            mw, mh = branch_w * 0.62, 6.5
            ax.add_patch(FancyBboxPatch((x - mw / 2, yy - mh / 2), mw, mh,
                         boxstyle="round,pad=0.3,rounding_size=1.4",
                         fill=True, fc=SLATE, ec="#0B1220", lw=1.4, zorder=5))
            ax.text(x, yy + 1.0, "MEDIDOR", ha="center", fontsize=6.3, fontweight="bold",
                    color="white", zorder=6)
            ax.text(x, yy - 1.6, medidor, ha="center", fontsize=6.0, color="#36DF8F",
                    family="monospace", zorder=6)
            yy -= mh / 2 + 2

        cond = ram.get("conductor")
        if cond:
            ax.text(x + 1.0, (yy + y_load + 8) / 2, cond, ha="left", va="center",
                    fontsize=6.2, color="#555555", style="italic", rotation=90)

        ax.plot([x, x], [yy, y_load + 8], color=INK, lw=1.6, zorder=2)

        bw, bh = branch_w * 0.82, 8
        ax.add_patch(FancyBboxPatch((x - bw / 2, y_load - bh / 2), bw, bh,
                     boxstyle="round,pad=0.35,rounding_size=1.6",
                     fill=True, fc=SLATE, ec=SLATE_ED, lw=1.6, zorder=5))
        ax.text(x, y_load, ram.get("carga", "Carga"), ha="center", va="center",
                fontsize=7.4, fontweight="bold", color="white", zorder=6)

    # ---------- tabla de convenciones ----------
    lx0, lx1, ly0, ly1 = 2, legend_w - 2, 2, 34
    ax.add_patch(FancyBboxPatch((lx0, ly0), lx1 - lx0, ly1 - ly0,
                 boxstyle="round,pad=0.5,rounding_size=1.8",
                 fill=True, fc="#FAFAFA", ec="#2B2B2B", lw=1.3, zorder=7))
    ax.text((lx0 + lx1) / 2, ly1 - 3, "CONVENCIONES", ha="center", fontsize=8.6,
            fontweight="bold", color=INK, zorder=8)
    conv_items = [
        ("Fusible / cortacircuitos", lambda x, y: _u_fuse(ax, x, y, INK, 0.6)),
        ("Seccionador",              lambda x, y: _u_disc(ax, x, y, INK, 0.6)),
        ("Transformador",            lambda x, y: _u_xfmr(ax, x, y, INK, 0.55, False)),
        ("Interruptor automatico",   lambda x, y: _u_breaker(ax, x, y, INK, 0.6)),
        ("TC (medicion)",            lambda x, y: _u_ct(ax, x, y, COL["R"], 0.55)),
        ("Carga / tablero",          lambda x, y: ax.add_patch(
            FancyBboxPatch((x - 2.6, y - 1.6), 5.2, 3.2, boxstyle="round,pad=0.15",
                           fill=True, fc=SLATE, ec=SLATE_ED, lw=1.0, zorder=8))),
    ]
    sx, tx = lx0 + 4.5, lx0 + 9
    item_ys = np.linspace(ly1 - 6.5, ly0 + 2.5, len(conv_items))
    for (lbl, draw_sym), yy in zip(conv_items, item_ys):
        draw_sym(sx, yy)
        ax.text(tx, yy, lbl, ha="left", va="center", fontsize=6.6, color=INK, zorder=8)

    plt.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white", pad_inches=0.3)
    plt.close(fig)
    return out_path

# ---------- pruebas ----------
if __name__=="__main__":
    import os; base=os.path.dirname(os.path.abspath(__file__))
    draw(dict(sistema="tri4h",tipo="indirecta",norma="CENS",rel_tc="200/5",rel_tp="13200/120"),
         os.path.join(base,"muestra_indirecta_3el.png"))
    draw(dict(sistema="tri3h",tipo="indirecta",norma="RA8",rel_tc="100/5",rel_tp="7620/120"),
         os.path.join(base,"muestra_indirecta_2el.png"))
    draw(dict(sistema="tri4h",tipo="semidirecta",norma="RA8",rel_tc="300/5"),
         os.path.join(base,"muestra_semidirecta_3el.png"))
    draw(dict(sistema="tri4h",tipo="indirecta",norma="RA8",respaldo=True,rel_tc="200/5",rel_tp="13200/120"),
         os.path.join(base,"muestra_respaldo_3el.png"))
    draw(dict(sistema="mono",tipo="directa",norma="RA8"),os.path.join(base,"muestra_monofasica.png"))
    draw_unifilar(dict(sistema="tri4h",tipo="indirecta",norma="CENS",rel_tc="200/5",rel_tp="13200/120",proyecto="Subestacion Cliente X"),
         os.path.join(base,"muestra_unifilar_indirecta.png"))
    draw_unifilar(dict(sistema="tri4h",tipo="semidirecta",norma="RA8",rel_tc="300/5"),
         os.path.join(base,"muestra_unifilar_semidirecta.png"))
    draw_unifilar_tablero(dict(
        proyecto="Subestacion Cliente X", circuito_entrada="Cto X-01",
        proteccion_primaria="Fusible 15 kV", trafo_kva="150", trafo_serie="#12345",
        interruptor_principal="3x600 A", bus_voltaje="220/127 V",
        ramales=[
            dict(proteccion="3x400 A", medicion="TC 400/5 A + CEM", conductor="3 N.2/0", carga="Tablero Principal"),
            dict(medidor="kWh", carga="Bombeo / Servicios"),
            dict(proteccion="3x150 A", conductor="3 N.2", carga="Iluminacion Comun"),
        ]), os.path.join(base,"muestra_unifilar_tablero.png"))
    print("OK todas")
