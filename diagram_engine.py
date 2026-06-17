# -*- coding: utf-8 -*-
"""
Motor de diagramas para sistemas de medida de energia.
  draw(cfg, out)          -> diagrama de CONEXIONES (Medidor <-> Bloque <-> TC/TP)
  draw_unifilar(cfg, out) -> diagrama UNIFILAR tecnico de la medida

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

def _pt(ax, x, ytop, ybot, color, label):
    """Transformador de tension entre fase y neutro (dos circulos verticales)."""
    ym=(ytop+ybot)/2
    ax.plot([x,x],[ytop,ym+2.2],color=color,lw=1.7,zorder=4)
    ax.plot([x,x],[ym-2.2,ybot],color=color,lw=1.7,zorder=4)
    ax.add_patch(Circle((x,ym+1.0),1.25,fill=False,ec=color,lw=1.8,zorder=5))
    ax.add_patch(Circle((x,ym-1.0),1.25,fill=False,ec=color,lw=1.8,zorder=5))
    ax.text(x+1.9,ym,label,ha="left",va="center",fontsize=7.5,color=color,fontweight="bold")

def _ground(ax, x, y, s=1.0):
    ax.plot([x,x],[y,y-1.2*s],color=COL["G"],lw=1.4)
    for i,w in enumerate([2.0,1.3,0.7]):
        ax.plot([x-w*s,x+w*s],[y-(1.2+0.5*i)*s]*2,color=COL["G"],lw=1.4)

# ============================================================
#  DIAGRAMA DE CONEXIONES (OBSOLETO — usar draw_conexiones_retie)
# ============================================================
def draw(cfg, out_path):
    """OBSOLETO: esta función se mantiene solo por compatibilidad.
    En producción se usa draw_conexiones_retie(). Actualizar tests."""
    sistema=cfg.get("sistema","tri4h"); tipo=cfg.get("tipo","indirecta")
    respaldo=bool(cfg.get("respaldo",False)); norma=cfg.get("norma","RA8")
    rel_tc=cfg.get("rel_tc",""); rel_tp=cfg.get("rel_tp",""); proyecto=cfg.get("proyecto","")
    has_tc=tipo in ("semidirecta","indirecta"); has_tp=tipo=="indirecta"

    terms=meter_terminals(sistema,norma); n=len(terms)
    cur_ph=current_phases(sistema); all_ph=phases_of(sistema)

    fig,ax=plt.subplots(figsize=(17,11)); ax.set_xlim(0,178); ax.set_ylim(0,116); ax.axis("off")

    titulo=f"DIAGRAMA DE CONEXIONES   ·   MEDIDA {tipo.upper()}   ·   {SIS_TXT[sistema]}"
    if respaldo: titulo+="   ·   PRINCIPAL + RESPALDO"
    ax.text(89,112,titulo,ha="center",va="center",fontsize=15,fontweight="bold",color=INK)
    sub=f"Norma {norma}"
    if rel_tc: sub+=f"      RTC {rel_tc}"
    if rel_tp: sub+=f"      RTP {rel_tp}"
    if proyecto: sub+=f"      {proyecto}"
    ax.text(89,107.5,sub,ha="center",va="center",fontsize=10.5,color="#666")

    # ---------- PRIMARIO ----------
    x0,x1=6,40; base_y=104; dy=8
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

    tc_x=14
    if has_tc:
        for ph in cur_ph: _ct(ax,tc_x,y_ph[ph],COL[ph],f"TC-{ph}")
    tp_c={}
    if has_tp:
        for i,ph in enumerate(all_ph):
            cx=22+i*6.5; tp_c[ph]=cx
            yref=y_N if show_N else min(y_ph.values())-5
            _pt(ax,cx,y_ph[ph],yref,COL[ph],f"TP-{ph}")

    # ---------- BLOQUE DE PRUEBA ----------
    bx0,bx1=70,96
    step=min(8.4,(96-12)/max(n,1))
    by1=98; by0=by1-(n*step)-4
    ax.add_patch(FancyBboxPatch((bx0,by0),bx1-bx0,by1-by0,boxstyle="round,pad=0.5,rounding_size=2.5",
                 fill=True,fc="#EEF2F6",ec="#2B2B2B",lw=2,zorder=1))
    blab="BLOQUE DE PRUEBA  "+("(13 term.)" if norma=="CENS" else "(B1–B26)")
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

    # ---------- MEDIDOR(ES) ----------
    def draw_meter(mx0,mx1,my0,my1,etq):
        ax.add_patch(FancyBboxPatch((mx0,my0),mx1-mx0,my1-my0,boxstyle="round,pad=0.6,rounding_size=3",
                     fill=True,fc=INK,ec="#0B0F14",lw=2,zorder=2))
        ax.text((mx0+mx1)/2,my1-4.5,etq,ha="center",va="center",fontsize=12,fontweight="bold",color="white")
        ax.add_patch(Rectangle((mx0+6,my1-17),(mx1-mx0)-12,7,fc="#0B3D2E",ec="#0A5",lw=1))
        ax.text((mx0+mx1)/2,my1-13.5,"kWh   kvarh",ha="center",va="center",fontsize=8.5,
                color="#36df8f",family="monospace")
        m_y={}; ty=np.linspace(my0+5,my0+5+(n-1)*3.3,n)[::-1]; mxr=mx0+2.4
        for (tlbl,rot,kind,ph,io),yy in zip(terms,ty):
            c=COL[ph]
            ax.add_patch(Circle((mxr,yy),0.85,fc="white",ec=c,lw=1.7,zorder=5))
            ax.text(mxr+1.6,yy,tlbl,ha="left",va="center",fontsize=7,color="white",fontweight="bold")
            m_y[tlbl]=yy
        return m_y,mxr
    mh=max(n*3.3+24,42); my1=98
    if not respaldo:
        meters=[draw_meter(130,162,my1-mh,my1,"MEDIDOR")]
    else:
        h=mh*0.5
        meters=[draw_meter(132,162,60,60+h,"PRINCIPAL"),
                draw_meter(132,162,10,10+h,"RESPALDO")]

    # ---------- RUTEO PRIMARIO -> BLOQUE ----------
    src={}
    for (tlbl,rot,kind,ph,io) in terms:
        if kind=="I" and has_tc:
            sx=tc_x-1.0 if io=="in" else tc_x+1.0
            src[tlbl]=(sx,y_ph[ph]-1.3)
        elif kind=="I":
            src[tlbl]=(tc_x,y_ph[ph])
        elif kind=="V" and ph=="N":
            src[tlbl]=(20,y_N if show_N else min(y_ph.values())-5)
        elif kind=="V" and has_tp:
            cx=tp_c[ph]; yref=y_N if show_N else min(y_ph.values())-5
            src[tlbl]=(cx,(y_ph[ph]+yref)/2)
        else:
            src[tlbl]=(tc_x+(1.0 if has_tc else 0),y_ph[ph])
    order=[t[0] for t in terms]
    lane_x=dict(zip(order,np.linspace(44,64,n)))
    rail_y=dict(zip(order,np.linspace(by1-3,by0+3,n)))
    for tlbl in order:
        sx,sy=src[tlbl]; lx=lane_x[tlbl]; ry=rail_y[tlbl]
        ty=row[tlbl][0]; ph=row[tlbl][1]; c=COL[ph]
        ls=(0,(6,3)) if ph=="N" else "-"
        w=2.3 if row[tlbl][2]=="I" else 1.7
        ax.plot([sx,sx],[sy,ry],color=c,lw=w,ls=ls)
        ax.plot([sx,lx],[ry,ry],color=c,lw=w,ls=ls)
        ax.plot([lx,lx],[ry,ty],color=c,lw=w,ls=ls)
        ax.plot([lx,xL],[ty,ty],color=c,lw=w,ls=ls)

    # ---------- BLOQUE -> MEDIDOR(ES) ----------
    xfan=np.linspace(100,128,n)
    for idx,tlbl in enumerate(order):
        yb=row[tlbl][0]; ph=row[tlbl][1]; c=COL[ph]
        ls=(0,(6,3)) if ph=="N" else "-"; xm=xfan[idx]
        ax.plot([xR,xm],[yb,yb],color=c,lw=1.7,ls=ls)
        for (m_y,mxr) in meters:
            ym=m_y[tlbl]
            ax.plot([xm,xm],[yb,ym],color=c,lw=1.5,ls=ls)
            ax.plot([xm,mxr],[ym,ym],color=c,lw=1.5,ls=ls)

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
#  SIMBOLOS IEC 60617 (para unifilar)
# ============================================================
def _u_breaker(ax,x,y,c=INK,s=1.0):
    """Interruptor automatico: cuadrado sobre la linea."""
    ax.add_patch(Rectangle((x-1.7*s,y-1.9*s),3.4*s,3.8*s,fill=False,ec=c,lw=2.2,zorder=4))

def _u_disc(ax,x,y,c=INK,s=1.0):
    """Seccionador: cuchilla abierta con pivote."""
    ax.add_patch(Circle((x,y-2.0*s),0.4,fc=c,ec=c,zorder=5))
    ax.add_patch(Circle((x,y+2.0*s),0.4,fc=c,ec=c,zorder=5))
    ax.plot([x,x+2.3*s],[y-2.0*s,y+1.6*s],color=c,lw=2.2,zorder=4)

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

def _u_xfmr(ax,x,y,c=INK,s=1.0):
    """Transformador de potencia: dos circulos entrelazados."""
    ax.add_patch(Circle((x,y+1.5*s),2.2*s,fill=False,ec=c,lw=2.2,zorder=4))
    ax.add_patch(Circle((x,y-1.5*s),2.2*s,fill=False,ec=c,lw=2.2,zorder=4))

def _u_relay(ax,x,y,c="#6A1B9A",funcs="50/51",s=1.0):
    """Rele de proteccion: circulo con funciones ANSI."""
    ax.add_patch(Circle((x,y),2.6*s,fill=False,ec=c,lw=2,zorder=4))
    ax.text(x,y,funcs,ha="center",va="center",fontsize=6.8,color=c,fontweight="bold",zorder=5)

def _u_meter(ax,x,y,w=22,h=12):
    ax.add_patch(FancyBboxPatch((x,y-h/2),w,h,boxstyle="round,pad=0.4,rounding_size=2",
                 fill=True,fc=INK,ec="#0B0F14",lw=2,zorder=5))
    ax.text(x+w/2,y+h*0.18,"MEDIDOR",ha="center",fontsize=9.5,fontweight="bold",color="white",zorder=6)
    ax.text(x+w/2,y-h*0.22,"kWh / kvarh",ha="center",fontsize=7.5,color="#36df8f",
            family="monospace",zorder=6)

# ============================================================
#  DIAGRAMA UNIFILAR (OBSOLETO — usar draw_unifilar_generico)
# ============================================================
def draw_unifilar(cfg, out_path):
    """OBSOLETO: esta función se mantiene solo por compatibilidad.
    En producción se usa draw_unifilar_generico()."""
    tipo=cfg.get("tipo","indirecta"); sistema=cfg.get("sistema","tri4h")
    norma=cfg.get("norma","RA8"); rel_tc=cfg.get("rel_tc",""); rel_tp=cfg.get("rel_tp","")
    proyecto=cfg.get("proyecto",""); tension=cfg.get("tension","")
    incluir_dps=cfg.get("dps", tipo=="indirecta")
    incluir_rele=cfg.get("rele", False)
    rele_funcs=cfg.get("rele_funcs","50/51")
    es_mt=(tipo=="indirecta")
    nfases="3F" if sistema in ("tri3h","tri4h") else ("2F" if sistema=="bifasico" else "1F")
    if not tension: tension="13.2 kV" if es_mt else "208/120 V"

    fig,ax=plt.subplots(figsize=(13,12)); ax.set_xlim(0,128); ax.set_ylim(0,150)
    ax.set_aspect("equal"); ax.axis("off")

    ax.text(64,146,"DIAGRAMA UNIFILAR DE MEDIDA",ha="center",fontsize=16,fontweight="bold",color=INK)
    sub=f"Medida {tipo} · {SIS_TXT[sistema].split(' (')[0].title()} · {tension} · Norma {norma}"
    ax.text(64,141,sub,ha="center",fontsize=10,color="#666")
    if proyecto: ax.text(64,137,proyecto,ha="center",fontsize=9,color="#888",style="italic")

    xc=46  # eje del unifilar
    def vline(y1,y2,lw=2.6): ax.plot([xc,xc],[y1,y2],color=INK,lw=lw,zorder=2)
    def busbar(yy,label,extra=""):
        ax.plot([xc-15,xc+15],[yy,yy],color=INK,lw=4.5,zorder=2)
        ax.text(xc-17,yy,label,ha="right",va="center",fontsize=10,fontweight="bold",color=INK)
        if extra: ax.text(xc+17,yy,extra,ha="left",va="center",fontsize=8.5,color="#777")

    y=130; busbar(y,"RED",tension); top=y
    # numero de conductores (marca diagonal)
    ax.plot([xc-2.6,xc+2.6],[y-5+1.3,y-5-1.3],color=INK,lw=1.4)
    ax.text(xc+4,y-5,nfases,ha="left",va="center",fontsize=8,color="#666")

    # Pararrayos / DPS (rama a la izquierda en MT)
    if incluir_dps:
        dx=xc-15
        ax.plot([xc,dx],[y-9,y-9],color=COL["G"],lw=1.6)
        _u_arrester(ax,dx,y-13.5,COL["G"],1.0)
        ax.text(dx-3,y-12,"Pararrayos\n(DPS)",ha="right",va="center",fontsize=8,color=COL["G"],fontweight="bold")
    y-=12; vline(top,y)

    # Cortacircuitos fusible (MT) o Interruptor (BT)
    if es_mt:
        _u_fuse(ax,xc,y-3,INK,1.0); ax.text(xc+5,y-3,"Cortacircuitos\nfusible (MT)",ha="left",va="center",fontsize=8.5,color=INK)
    else:
        _u_breaker(ax,xc,y-3,INK,1.0); ax.text(xc+5,y-3,"Interruptor\nprincipal (BT)",ha="left",va="center",fontsize=8.5,color=INK)
    y2=y-6; vline(y,y2); y=y2-8; vline(y2,y)

    nodo=y; ax.add_patch(Circle((xc,nodo),0.9,fc=INK,ec=INK,zorder=4))

    # TP de medida (indirecta)
    if tipo=="indirecta":
        tpx=xc-20
        ax.plot([xc,tpx],[nodo,nodo],color=COL["S"],lw=1.8)
        ax.plot([tpx,tpx],[nodo,nodo-3.0],color=COL["S"],lw=1.8)
        _u_vt(ax,tpx,nodo-5.2,COL["S"],1.0,ground=True)
        ax.text(tpx-3,nodo-3,f"TP {nfases}\n{rel_tp or '—'}",ha="right",va="center",
                fontsize=8,color=COL["S"],fontweight="bold")
    # TC de medida (serie)
    if tipo in ("indirecta","semidirecta"):
        _u_ct(ax,xc,nodo-6,COL["R"],1.0)
        ax.text(xc+4,nodo-6,f"TC {nfases}\n{rel_tc or '—'}",ha="left",va="center",
                fontsize=8,color=COL["R"],fontweight="bold")
        y=nodo-11
    else:
        y=nodo-4
    vline(nodo,y)

    # Rele de proteccion (opcional) - linea de control punteada al fusible/interruptor
    if incluir_rele:
        rx=64
        _u_relay(ax,rx,nodo-8.5,"#6A1B9A",rele_funcs,1.0)
        ax.text(rx,nodo-12.5,"Relé prot.",ha="center",va="top",fontsize=7.5,color="#6A1B9A",fontweight="bold")
        ax.plot([xc+2.1,rx],[nodo-6,nodo-6],color="#6A1B9A",lw=1.2,ls=":")             # toma de TC
        ax.plot([rx,rx],[nodo-6,nodo-5.9],color="#6A1B9A",lw=1.2,ls=":")
        ax.plot([rx,rx],[nodo-11.1,nodo-6],color="#6A1B9A",lw=1.2,ls=":")             # al circulo
        ax.plot([xc+2.1,rx],[y2-3,y2-3],color="#6A1B9A",lw=1.2,ls=":")                # disparo a fusible
        ax.plot([rx,rx],[y2-3,nodo-5.9],color="#6A1B9A",lw=1.2,ls=":")

    # Medidor (a la izquierda) + senales punteadas
    my=nodo-6; _u_meter(ax,6,my,22,12)
    ax.annotate("",xy=(28,my+1.5),xytext=(xc-2,nodo-6),
                arrowprops=dict(arrowstyle="-|>",color=COL["R"],ls=":",lw=1.5))
    if tipo=="indirecta":
        ax.annotate("",xy=(28,my-1.5),xytext=(xc-20,nodo-3),
                    arrowprops=dict(arrowstyle="-|>",color=COL["S"],ls=":",lw=1.5))
    elif tipo=="semidirecta":
        ax.annotate("",xy=(28,my-1.5),xytext=(xc-0.5,nodo),
                    arrowprops=dict(arrowstyle="-|>",color=COL["S"],ls=":",lw=1.4))
    ax.text(17,my-8.5,"señales de medida (I y V)",ha="center",fontsize=7,color="#888",style="italic")

    # Transformador de potencia (MT) y barra BT, luego carga
    if es_mt:
        ty=y-9; vline(y,ty); _u_xfmr(ax,xc,ty-3,INK,1.0)
        ax.text(xc+5,ty-3,"Transformador\nde potencia",ha="left",va="center",fontsize=8.5,color=INK)
        y=ty-7; vline(ty,y); busbar(y,"BT","208/120 V"); y-=9; vline(y+9,y)
    ax.add_patch(Polygon([[xc-4,y],[xc+4,y],[xc,y-7]],closed=True,fill=False,ec=INK,lw=2.2))
    ax.text(xc,y-9,"CARGA",ha="center",va="top",fontsize=9.5,fontweight="bold",color=INK)

    # ---------------- PLANO DE SIMBOLOGIA ----------------
    px0,px1=78,126; py1=128; py0=44
    ax.add_patch(FancyBboxPatch((px0,py0),px1-px0,py1-py0,boxstyle="round,pad=0.6,rounding_size=2",
                 fill=False,ec="#2B2B2B",lw=1.6))
    ax.text((px0+px1)/2,py1-3,"PLANO DE SIMBOLOGÍA",ha="center",fontsize=11,fontweight="bold",color=INK)
    ax.text((px0+px1)/2,py1-6.5,"IEC / UNE 60617",ha="center",fontsize=8,color="#888",style="italic")

    items=[("Cortacircuitos fusible (MT)", lambda x,y:_u_fuse(ax,x,y,INK,0.9)),
           ("Interruptor automático",      lambda x,y:_u_breaker(ax,x,y,INK,0.9)),
           ("Seccionador",                 lambda x,y:_u_disc(ax,x,y,INK,0.9)),
           ("Pararrayos / DPS",            lambda x,y:_u_arrester(ax,x,y,COL["G"],0.9)),
           ("Transformador de corriente",  lambda x,y:_u_ct(ax,x,y,COL["R"],0.9)),
           ("Transformador de tensión",    lambda x,y:_u_vt(ax,x,y,COL["S"],0.9,False)),
           ("Transformador de potencia",   lambda x,y:_u_xfmr(ax,x,y,INK,0.8)),
           ("Relé de protección (ANSI)",   lambda x,y:_u_relay(ax,x,y,"#6A1B9A","50/51",0.85)),
           ("Puesta a tierra",             lambda x,y:_ground(ax,x,y+2,0.7)),
           ("Barra / barraje",             lambda x,y:ax.plot([x-3.5,x+3.5],[y,y],color=INK,lw=4)),
           ("Carga",                       lambda x,y:ax.add_patch(Polygon([[x-2.4,y+2.2],[x+2.4,y+2.2],[x,y-2.2]],closed=True,fill=False,ec=INK,lw=1.8)))]
    sx=px0+9; tx=px0+16
    ys2=np.linspace(py1-14,py0+6,len(items))
    for (label,draw_sym),yy in zip(items,ys2):
        draw_sym(sx,yy)
        ax.text(tx,yy,label,ha="left",va="center",fontsize=8.3,color=INK)
    ax.text((px0+px1)/2,py0+1.5,"ANSI: 27 mín. tensión · 49 temperatura · 50/51 sobreintensidad",
            ha="center",va="bottom",fontsize=6.0,color="#888")

    plt.savefig(out_path,dpi=160,bbox_inches="tight",facecolor="white"); plt.close(fig)
    return out_path


# ============================================================
#  UNIFILAR "REAL" (OBSOLETO — lógica integrada en draw_unifilar_generico)
# ============================================================
def draw_unifilar_trafo(cfg, out_path):
    """OBSOLETO: esta función se mantiene solo por compatibilidad.
    En producción se usa draw_unifilar_generico() con instalacion='trafo'."""
    """
    MT -> N cortacircuitos -> transformador -> barra BT -> N TC -> medidor
                                                         -> interruptor/totalizador -> carga
    cfg admite:
      v_mt='13.200 V', n_cc=3, trafo_kva='20', trafo_tipo='bifasico',
      v_bt='240/120 V', n_tc=2, rel_tc='200/5', interruptor='200 A', proyecto=''
    """
    v_mt=cfg.get("v_mt","13.200 V"); n_cc=int(cfg.get("n_cc",3))
    kva=cfg.get("trafo_kva","20"); ttipo=cfg.get("trafo_tipo","bifasico")
    v_bt=cfg.get("v_bt","240/120 V"); n_tc=int(cfg.get("n_tc",2))
    rel_tc=cfg.get("rel_tc","200/5"); interruptor=cfg.get("interruptor","200 A")
    proyecto=cfg.get("proyecto","")

    fig,ax=plt.subplots(figsize=(13,12)); ax.set_xlim(0,128); ax.set_ylim(0,150)
    ax.set_aspect("equal"); ax.axis("off")
    ax.text(64,146,"DIAGRAMA UNIFILAR DE MEDIDA",ha="center",fontsize=16,fontweight="bold",color=INK)
    ax.text(64,141,f"Medida semidirecta en secundario · Transformador {ttipo} {kva} kVA · Norma {cfg.get('norma','RA8')}",
            ha="center",fontsize=10,color="#666")
    if proyecto: ax.text(64,137,proyecto,ha="center",fontsize=9,color="#888",style="italic")

    xc=44
    def vline(y1,y2,lw=2.6): ax.plot([xc,xc],[y1,y2],color=INK,lw=lw,zorder=2)
    def busbar(yy,label,extra=""):
        ax.plot([xc-15,xc+15],[yy,yy],color=INK,lw=4.5,zorder=2)
        ax.text(xc-17,yy,label,ha="right",va="center",fontsize=10,fontweight="bold",color=INK)
        if extra: ax.text(xc+17,yy,extra,ha="left",va="center",fontsize=9,color="#777")

    # --- RED MT ---
    busbar(132,"RED M.T.",v_mt)
    # --- N cortacircuitos ---
    xs=[xc+(i-(n_cc-1)/2)*8 for i in range(n_cc)]
    for x in xs:
        ax.plot([x,x],[132,128],color=INK,lw=2.2)
        _u_fuse(ax,x,125,INK,0.85)
        ax.plot([x,x],[122.8,118],color=INK,lw=2.2)
    ax.plot([xs[0],xs[-1]],[118,118],color=INK,lw=2.6)
    ax.text(xs[-1]+3,123,f"{n_cc} Cortacircuitos\nfusible (MT)",ha="left",va="center",fontsize=8.5,color=INK)
    vline(118,112)

    # --- Transformador ---
    _u_xfmr(ax,xc,108,INK,1.35)
    ax.text(xc+7,108,f"Transformador {ttipo}\n{kva} kVA · {cfg.get('v_mt','13.2 kV').split()[0]}/{v_bt}",
            ha="left",va="center",fontsize=8.5,color=INK,fontweight="bold")
    vline(112,108+2.0*1.35)  # a primario
    vline(108-2.0*1.35,99)   # de secundario a barra BT

    # --- Barra BT ---
    busbar(99,"BARRA B.T.",v_bt)
    vline(99,94)

    # --- Nodo + N TC ---
    nodo=94; ax.add_patch(Circle((xc,nodo),0.9,fc=INK,ec=INK,zorder=4))
    _u_ct(ax,xc,nodo-5,COL["R"],1.0)
    ax.text(xc+4,nodo-5,f"{n_tc} TC {rel_tc}",ha="left",va="center",fontsize=9,color=COL["R"],fontweight="bold")
    vline(nodo,nodo-10)
    y=nodo-10

    # --- Medidor (izquierda) + senales ---
    my=nodo-5; _u_meter(ax,4,my,24,12)
    ax.annotate("",xy=(28,my+1.6),xytext=(xc-2,nodo-5),
                arrowprops=dict(arrowstyle="-|>",color=COL["R"],ls=":",lw=1.6))   # I de los TC
    ax.annotate("",xy=(28,my-1.6),xytext=(xc-0.6,nodo+0.2),
                arrowprops=dict(arrowstyle="-|>",color=COL["S"],ls=":",lw=1.5))   # V directa de la barra
    ax.text(16,my-8.2,"señales de medida\nI (TC) + V (directa)",ha="center",fontsize=7.2,color="#888",style="italic")

    # --- Interruptor / Totalizador ---
    _u_breaker(ax,xc,y-3,INK,1.05)
    ax.text(xc+5,y-3,f"Totalizador /\nInterruptor {interruptor}",ha="left",va="center",fontsize=8.5,color=INK,fontweight="bold")
    y2=y-6; vline(y,y2); y=y2-8; vline(y2,y)

    # --- Carga ---
    ax.add_patch(Polygon([[xc-4,y],[xc+4,y],[xc,y-7]],closed=True,fill=False,ec=INK,lw=2.2))
    ax.text(xc,y-9,"CARGA",ha="center",va="top",fontsize=9.5,fontweight="bold",color=INK)

    # ---------------- PLANO DE SIMBOLOGIA ----------------
    px0,px1=78,126; py1=128; py0=46
    ax.add_patch(FancyBboxPatch((px0,py0),px1-px0,py1-py0,boxstyle="round,pad=0.6,rounding_size=2",
                 fill=False,ec="#2B2B2B",lw=1.6))
    ax.text((px0+px1)/2,py1-3,"PLANO DE SIMBOLOGÍA",ha="center",fontsize=11,fontweight="bold",color=INK)
    ax.text((px0+px1)/2,py1-6.5,"IEC / UNE 60617",ha="center",fontsize=8,color="#888",style="italic")
    items=[("Cortacircuitos fusible (MT)", lambda x,y:_u_fuse(ax,x,y,INK,0.9)),
           ("Transformador de potencia",   lambda x,y:_u_xfmr(ax,x,y,INK,0.85)),
           ("Transformador de corriente",  lambda x,y:_u_ct(ax,x,y,COL["R"],0.9)),
           ("Interruptor / totalizador",   lambda x,y:_u_breaker(ax,x,y,INK,0.9)),
           ("Medidor de energía",          lambda x,y:(ax.add_patch(Rectangle((x-3,y-2),6,4,fill=True,fc=INK,ec=INK)))),
           ("Barra / barraje",             lambda x,y:ax.plot([x-3.5,x+3.5],[y,y],color=INK,lw=4)),
           ("Puesta a tierra",             lambda x,y:_ground(ax,x,y+2,0.7)),
           ("Carga",                       lambda x,y:ax.add_patch(Polygon([[x-2.4,y+2.2],[x+2.4,y+2.2],[x,y-2.2]],closed=True,fill=False,ec=INK,lw=1.8)))]
    sx=px0+9; tx=px0+16
    ys2=np.linspace(py1-14,py0+8,len(items))
    for (label,dsym),yy in zip(items,ys2):
        dsym(sx,yy); ax.text(tx,yy,label,ha="left",va="center",fontsize=8.4,color=INK)

    plt.savefig(out_path,dpi=160,bbox_inches="tight",facecolor="white"); plt.close(fig)
    return out_path




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
        ax.text(bx[i], BORN_Y - BORN_R - 1.5, lbl,
                ha="center", va="top", fontsize=5.5, color=c, zorder=5)

    # ── Lanes de conductores (debajo del medidor) ──────────────────────────
    LANE_Y_TOP = BORN_Y - BORN_R - 10  # primera lane justo bajo la bornera
    lane_y = {}
    for ki, cond in enumerate(conductores):
        lane_y[cond] = LANE_Y_TOP - ki * LANE_SEP

    X_ACO = 8    # x inicio lineas acometida
    X_CAR = W-8  # x fin lineas carga

    for cond in conductores:
        c  = COL.get(cond, "#333")
        ly = lane_y[cond]
        lw = 2.2 if cond != "N" else 1.8
        ls = "-" if cond != "N" else (0,(5,2))
        lbl = "Neutro" if cond == "N" else f"Fase {cond}"

        # Etiquetas
        ax.text(X_ACO - 1, ly, lbl, ha="right", va="center",
                fontsize=8.5, fontweight="bold", color=c)
        ax.text(X_CAR + 1, ly, lbl, ha="left", va="center",
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
            ax.plot([sx, sx],    [BORN_Y - BORN_R, ly], color=c, lw=lw, ls=ls, zorder=2)
            ax.plot([sx, X_CAR], [ly, ly], color=c, lw=lw, ls=ls, zorder=2)

    # Buses verticales acometida y carga
    ys_all = list(lane_y.values())
    bus_top = max(ys_all) + 2; bus_bot = min(ys_all) - 2
    ax.plot([X_ACO, X_ACO], [bus_bot, bus_top], color="#AAA", lw=0.7, zorder=1)
    ax.plot([X_CAR, X_CAR], [bus_bot, bus_top], color="#AAA", lw=0.7, zorder=1)
    ax.text(X_ACO-1, (bus_top+bus_bot)/2, "ACOMETIDA",
            ha="right", va="center", fontsize=7, color="#555", rotation=90)
    ax.text(X_CAR+1, (bus_top+bus_bot)/2, "CARGA",
            ha="left", va="center", fontsize=7, color="#555", rotation=90)

    # ── Bobinas I — una por fase, apiladas verticalmente ────────────────────
    COIL_R = 6.5
    coil_zone_bot = BORN_Y + BORN_R + COIL_R + 4   # coil bottom clears bornera top
    coil_zone_top = MY1 - 3
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
        ax.add_patch(Circle((tap_bx, tap_y), 1.6, fc=c, ec=c, zorder=7))
        ax.plot([tap_bx, tap_bx], [tap_y + 1.6, cy - COIL_R],
                color=c, lw=0.9, ls=(0,(3,2)), zorder=2)
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
    x0,x1=6,40; dy=8
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

    # TC en serie (con la linea de fase, hacia la carga)
    tc_x=14
    if has_tc:
        for ph in cur_ph: _ct(ax,tc_x,y_ph[ph],COL[ph],f"TC-{ph}")
    # TP en paralelo (fase->neutro)
    # G4: Aron (tri3h) usa solo 2 TP (fases R y T), no 3.
    # CREG 038/2014: medida 2 elementos = 2 TC + 2 TP.
    tp_phases = current_phases(sistema) if sistema == "tri3h" else all_ph
    tp_c={}
    if has_tp:
        for i,ph in enumerate(tp_phases):
            cx=22+i*6.5; tp_c[ph]=cx
            yref=y_N if show_N else min(y_ph.values())-5
            _pt(ax,cx,y_ph[ph],yref,COL[ph],f"TP-{ph}")

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
    #   "cierre_aron": bornera 4 del Aron recibe los 2 cierres (TC-R y TC-T)
    #   tension V : viene del secundario del TP correspondiente
    #   neutro N  : viene del secundario b/n de los TPs -> BN
    #   "puente"  : se puentea internamente en el medidor, NO recibe cable propio
    src={}
    for (tlbl,rot,kind,ph,io) in terms:
        if io == "puente":
            continue   # bornera puenteada internamente, sin cable al bloque
        if kind=="I" and io=="in" and has_tc:
            # Corriente: borne derecho del TC (salida) -> borne derecho del bloque
            sx=tc_x+1.0
            src[tlbl]=(sx, y_ph[ph]+1.3)
        elif kind=="I" and io=="cierre" and has_tc:
            # Cierre: borne izquierdo del TC (entrada) -> borne izquierdo del bloque
            sx=tc_x-1.0
            src[tlbl]=(sx, y_ph[ph]-1.3)
        elif kind=="I" and io=="cierre_aron" and has_tc:
            # Aron bornera 4: recibe los 2 cierres (TC-R y TC-T)
            # Se traza desde ambos TCs al mismo punto de la bornera
            src[tlbl]=(tc_x-1.0, y_ph["R"]-1.3)   # principal desde TC-R
            src[tlbl+"_T"]=(tc_x-1.0, y_ph["T"]-1.3)  # segundo desde TC-T
        elif kind=="I":
            src[tlbl]=(tc_x, y_ph.get(ph, list(y_ph.values())[0]))
        elif kind=="V" and ph=="N":
            src[tlbl]=(20, y_N if show_N else min(y_ph.values())-5)
        elif kind=="V" and has_tp and ph in tp_c:
            cx=tp_c[ph]; yref=y_N if show_N else min(y_ph.values())-5
            src[tlbl]=(cx,(y_ph[ph]+yref)/2)
        else:
            src[tlbl]=(tc_x+(1.0 if has_tc else 0), y_ph.get(ph, list(y_ph.values())[0]))

    order=[t[0] for t in terms if t[4] not in ("puente","puente_3")]
    lane_x=dict(zip(order,np.linspace(46,68,len(order))))
    rail_y=dict(zip(order,np.linspace(by1-3,by0+3,len(order))))
    for tlbl in order:
        if tlbl not in src:
            continue
        sx,sy=src[tlbl]; lx=lane_x[tlbl]; ry=rail_y[tlbl]
        by=row[tlbl][0]; ph=row[tlbl][1]; c=COL[ph]
        io=row[tlbl][4]
        ls=(0,(6,3)) if ph=="N" else "-"
        w=2.3 if row[tlbl][2]=="I" else 1.7
        # Corriente "in" sale del borne DERECHO del bloque (xR)
        # Cierre sale del borne IZQUIERDO del bloque (xL)
        bx = xR if io=="in" else xL
        ax.plot([sx,sx],[sy,ry],color=c,lw=w,ls=ls)
        ax.plot([sx,lx],[ry,ry],color=c,lw=w,ls=ls)
        ax.plot([lx,lx],[ry,by],color=c,lw=w,ls=ls)
        ax.plot([lx,bx],[by,by],color=c,lw=w,ls=ls)
        # Aron: segundo cierre (TC-T) también llega al borne 4 vía el puente de bornera
        # No se traza cable separado — el puente C1-C2 en la bornera lo une

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
        # Ruta: RESPALDO out → izquierda (fuera del medidor) → abajo bajo la caja
        #       → más a la izquierda → arriba hasta el borne cierre del bloque
        y_bus_base = 5   # bus horizontal por debajo de todo (cerca del fondo del canvas)

        for ci, (tlbl_out, ph) in enumerate(bornes_I_out.items()):
            if tlbl_out not in m_yr or tlbl_out not in row:
                continue
            yb_cierre = row[tlbl_out][0]   # borne cierre en el bloque
            ym_rout   = m_yr[tlbl_out]     # RESPALDO borne salida y
            x_out     = mx0_p - 4 - ci*2  # columna lateral izquierda del medidor
            y_bus     = y_bus_base - ci*2  # bus horizontal escalonado por fase
            xret      = xL - 3 - ci*2     # columna de retorno junto al bloque
            c = COL[ph]; ls = (0,(4,2))
            ax.plot([mxrr,  x_out],[ym_rout,  ym_rout],   color=c, lw=1.5, ls=ls)
            ax.plot([x_out, x_out],[ym_rout,  y_bus],     color=c, lw=1.5, ls=ls)
            ax.plot([x_out, xret], [y_bus,    y_bus],     color=c, lw=1.5, ls=ls)
            ax.plot([xret,  xret], [y_bus,    yb_cierre], color=c, lw=1.5, ls=ls)
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
def draw_unifilar_generico(cfg, out_path):
    """
    Linea principal vertical (xc=28): RED -> cortacircuito/seccionador -> trafo -> barra BT
                                           -> TC (BT si semidirecta) -> CARGA
    Circuito de medida (caja punteada a la DERECHA): sale del TC/nodo hacia la derecha.
    Panel derecho: plano de simbologia IEC/UNE 60617.
    """
    tipo        = cfg.get("tipo", "directa")
    sistema     = cfg.get("sistema", "tri4h")
    norma       = cfg.get("norma", "RA8")
    rel_tc      = cfg.get("rel_tc", "")
    rel_tp      = cfg.get("rel_tp", "")
    instalacion = cfg.get("instalacion", "barraje")
    respaldo    = bool(cfg.get("respaldo", False))
    kva         = cfg.get("trafo_kva", "")
    trafo_tipo  = cfg.get("trafo_tipo", "trifasico")
    n_trafos    = int(cfg.get("n_trafos", 1))
    interruptor = cfg.get("interruptor", "")

    fig, ax = plt.subplots(figsize=(14, 11))
    W, H = 135, 115
    ax.set_xlim(0, W); ax.set_ylim(0, H)
    ax.set_aspect("equal"); ax.axis("off")

    # Titulo
    ax.text(W/2, H-2, "DIAGRAMA UNIFILAR DE MEDIDA",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    tipo_txt = {"directa":"Directa","semidirecta":"Semidirecta","indirecta":"Indirecta"}[tipo]
    sis_short = SIS_TXT[sistema].split(" (")[0].title()
    sub_parts = [f"Medida {tipo_txt}", sis_short, f"Norma {norma}"]
    if rel_tc:  sub_parts.append(f"RTC {rel_tc}")
    if rel_tp:  sub_parts.append(f"RTP {rel_tp}")
    if respaldo: sub_parts.append("Principal + Respaldo")
    cal = cfg.get("calibre_conductor") or cfg.get("calibre_acometida")
    if cal: sub_parts.append(f"Calibre {cal}")
    ax.text(W/2, H-6, "  .  ".join(sub_parts),
            ha="center", fontsize=8.5, color="#666")

    xc = 28   # eje del unifilar
    y  = H - 12

    def vline(ya, yb, lw=2.6):
        ax.plot([xc, xc], [ya, yb], color=INK, lw=lw, zorder=2)

    def node_dot(yy):
        ax.add_patch(Circle((xc, yy), 0.85, fc=INK, ec=INK, zorder=4))

    def busbar(yy, label):
        ax.plot([xc-13, xc+13], [yy, yy], color=INK, lw=4.5, zorder=2)
        ax.text(xc-15, yy, label, ha="right", va="center",
                fontsize=9.5, fontweight="bold", color=INK)

    def draw_medida_box(tap_y):
        """Caja punteada a la derecha con bloque de prueba + medidor(es).
        La caja se centra en tap_y y NO se extiende hacia abajo del nivel TC,
        para evitar solaparse con el trafo o la carga que están debajo."""
        bx0 = xc + 5
        med_w = 16; bp_w = 10
        bx1 = bx0 + bp_w + 4 + med_w + 8

        # Centro de los elementos al mismo nivel que el TC
        bp_mid = tap_y
        # Altura de la caja centrada en tap_y
        half_h = 8 if not respaldo else 16
        by0 = tap_y - half_h   # solo sube/baja simétricamente
        by1 = tap_y + half_h

        # Rama horizontal (línea de señal desde TC secundario al circuito)
        ax.plot([xc, bx0], [tap_y, tap_y], color=INK, lw=1.8, zorder=2)

        # Caja punteada (circuito de medida)
        ax.add_patch(Rectangle((bx0, by0), bx1-bx0, by1-by0,
                     fill=False, ec="#555", lw=1.3, ls=(0,(5,3)), zorder=2))
        ax.text(bx0+1.5, by1-1, "Circuito de medida",
                fontsize=6, va="top", ha="left", color="#555", style="italic")

        # Bloque de prueba (centrado en tap_y)
        bp_x = bx0 + 3
        bp_h = min(12, half_h * 2 - 4)   # ajusta al espacio de la caja
        ax.add_patch(FancyBboxPatch((bp_x, bp_mid - bp_h/2), bp_w, bp_h,
                     boxstyle="round,pad=0.3,rounding_size=1",
                     fill=True, fc="#E8EFF7", ec="#444", lw=1.1, zorder=3))
        ax.text(bp_x+bp_w/2, bp_mid, f"BLOQUE\n{norma}",
                ha="center", va="center", fontsize=6, color="#222", fontweight="bold")

        # Alambre de bloque al medidor
        med_x0 = bp_x + bp_w + 3

        if not respaldo:
            ax.plot([bp_x+bp_w, med_x0], [bp_mid, bp_mid], color=INK, lw=1.3, zorder=3)
            med_h = min(12, half_h * 2 - 4)
            ax.add_patch(FancyBboxPatch((med_x0, bp_mid - med_h/2), med_w, med_h,
                         boxstyle="round,pad=0.3,rounding_size=1.5",
                         fill=True, fc=INK, ec="#0B0F14", lw=1.3, zorder=3))
            ax.text(med_x0+med_w/2, bp_mid+1.5, "MEDIDOR",
                    ha="center", va="center", fontsize=6.5, fontweight="bold", color="white")
            ax.add_patch(Rectangle((med_x0+2, bp_mid - med_h/2 + 1), med_w-4, 4,
                         fc="#0B3D2E", ec="#0A5", lw=0.7, zorder=4))
            ax.text(med_x0+med_w/2, bp_mid - med_h/2 + 3, "kWh",
                    ha="center", va="center", fontsize=5.5, color="#36df8f",
                    family="monospace", zorder=5)
        else:
            # PRINCIPAL arriba, RESPALDO abajo, dentro de la caja
            sep = half_h - 2
            y_p = bp_mid + sep/2
            y_c = bp_mid - sep/2
            med_h = min(9, sep - 2)

            jx = med_x0 - 1
            ax.plot([bp_x+bp_w, jx], [bp_mid, bp_mid], color=INK, lw=1.2, zorder=3)
            ax.plot([jx, jx], [y_p, y_c], color=INK, lw=1.2, zorder=3)
            ax.plot([jx, med_x0], [y_p, y_p], color=INK, lw=1.2, zorder=3)
            ax.plot([jx, med_x0], [y_c, y_c], color=INK, lw=1.0, ls=(0,(3,2)), zorder=3)

            for etq, my, fc in [("PRINCIPAL", y_p, INK), ("RESPALDO", y_c, "#1a3a6a")]:
                ax.add_patch(FancyBboxPatch((med_x0, my - med_h/2), med_w, med_h,
                             boxstyle="round,pad=0.3,rounding_size=1.5",
                             fill=True, fc=fc, ec="#0B0F14", lw=1.2, zorder=3))
                ax.text(med_x0+med_w/2, my, etq,
                        ha="center", va="center", fontsize=5.5,
                        fontweight="bold", color="white")

    # ── RED / Barra principal ──────────────────────────────────────────────────
    red_lbl = "RED (M.T.)" if tipo == "indirecta" else "RED (B.T.)"
    busbar(y, red_lbl)
    vline(y, y-6); y -= 6

    # ── INDIRECTA: TC + TP en MT antes del trafo ──────────────────────────────
    if tipo == "indirecta":
        # Seccionador / Cortacircuito MT (protección primaria antes de la medida)
        n_cc = int(cfg.get("n_cc", 1))
        cc_y = y - 3
        vline(y, cc_y)
        if n_cc >= 3:
            for dx in [-2.5, 0, 2.5]:
                _u_fuse(ax, xc+dx, cc_y, INK, 0.75)
            cc_lbl = f"{n_cc} Cortacircuitos MT"
        elif n_cc == 2:
            for dx in [-1.5, 1.5]:
                _u_fuse(ax, xc+dx, cc_y, INK, 0.75)
            cc_lbl = "2 Cortacircuitos MT"
        else:
            _u_disc(ax, xc, cc_y, INK, 1.0)
            cc_lbl = "Seccionador MT"
        ax.text(xc-6, cc_y, cc_lbl, ha="right", va="center",
                fontsize=7.5, color=INK, fontweight="bold")
        vline(cc_y, cc_y-4)
        y = cc_y - 4

        node_dot(y)
        vline(y, y-4)

        # TC en la linea principal
        tc_y = y - 4
        _u_ct(ax, xc, tc_y, COL["R"], 1.0)
        ax.text(xc-4, tc_y, f"TC (M.T.)\n{rel_tc or '---'}",
                ha="right", va="center", fontsize=8, color=COL["R"], fontweight="bold")

        # TP al mismo nivel del TC — rama izquierda desde el mismo nodo de medida
        node_dot(tc_y)
        tpx = xc - 18
        ax.plot([xc, tpx], [tc_y, tc_y], color=COL["S"], lw=1.5)
        ax.plot([tpx, tpx], [tc_y, tc_y-6], color=COL["S"], lw=1.5)
        _u_vt(ax, tpx, tc_y-6, COL["S"], 0.85, ground=True)
        ax.text(tpx-2, tc_y-6, f"TP (M.T.)\n{rel_tp or '---'}",
                ha="right", va="center", fontsize=8, color=COL["S"], fontweight="bold")

        # Caja de medida a la DERECHA del TC (TC+TP secundarios al circuito)
        draw_medida_box(tc_y)

        vline(y, y-9); y -= 9

    # ── TRAFO (instalacion=trafo) ──────────────────────────────────────────────
    if instalacion == "trafo":
        if tipo == "semidirecta":
            _u_disc(ax, xc, y-3, INK, 1.0)
            ax.text(xc-6, y-3, "Seccionador", ha="right", va="center",
                    fontsize=8, color=INK, fontweight="bold")
            vline(y, y-6); y -= 6

        trafo_y = y - 5
        kva_list = cfg.get("trafo_kva_list", [])

        def _banco_kva_lbl(n_t):
            if kva_list and len(kva_list) == n_t:
                if len(set(kva_list)) == 1:
                    return f"{n_t} x {kva_list[0]} kVA"
                return " + ".join(kva_list) + " kVA"
            return f"{n_t} x {kva} kVA" if kva else ""

        if n_trafos == 3:
            # Banco de 3 trafos (simbolos lado a lado)
            for dx in [-4.5, 0, 4.5]:
                ax.add_patch(Circle((xc+dx, trafo_y+2.2), 2.2, fill=False, ec=INK, lw=1.8))
                ax.add_patch(Circle((xc+dx, trafo_y-2.2), 2.2, fill=False, ec=INK, lw=1.8))
            k = _banco_kva_lbl(3)
            trafo_lbl = f"Banco 3 x trafo\n{k}" if k else "Banco 3 x trafo"
        elif n_trafos == 2:
            for dx in [-2.5, 2.5]:
                ax.add_patch(Circle((xc+dx, trafo_y+2.2), 2.2, fill=False, ec=INK, lw=1.8))
                ax.add_patch(Circle((xc+dx, trafo_y-2.2), 2.2, fill=False, ec=INK, lw=1.8))
            k = _banco_kva_lbl(2)
            trafo_lbl = f"Banco 2 x trafo\n{k}" if k else "Banco 2 x trafo"
        else:
            _u_xfmr(ax, xc, trafo_y, INK, 1.25)
            trafo_lbl = f"Trafo {trafo_tipo}"
            if kva: trafo_lbl += f"\n{kva} kVA"

        ax.text(xc-8, trafo_y, trafo_lbl,
                ha="right", va="center", fontsize=8.5, color=INK, fontweight="bold")
        vline(y, trafo_y-5); y = trafo_y - 6

        # Interruptor totalizador BT (entre trafo y barraje)
        if interruptor:
            int_y = y - 4
            vline(y, int_y - 3)
            _u_breaker(ax, xc, int_y, INK, 1.0)
            ax.text(xc-4, int_y, f"Int. Totalizador\n{interruptor}",
                    ha="right", va="center", fontsize=8, color=INK, fontweight="bold")
            y = int_y - 4

        busbar(y, "BARRA B.T.")
        vline(y, y-5); y -= 5

    # ── TC en BT (semidirecta) ────────────────────────────────────────────────
    if tipo == "semidirecta":
        node_dot(y)
        tc_y = y - 4
        _u_ct(ax, xc, tc_y, COL["R"], 1.0)
        ax.text(xc-4, tc_y, f"TC (B.T.)\n{rel_tc or '---'}",
                ha="right", va="center", fontsize=8, color=COL["R"], fontweight="bold")

        # Caja de medida a la DERECHA del TC
        draw_medida_box(tc_y)

        vline(y, y-9); y -= 9

    # ── DIRECTA: caja de medida directa ──────────────────────────────────────
    if tipo == "directa":
        draw_medida_box(y - 4)
        vline(y, y-10); y -= 10

    # ── Interruptor (solo si no hay trafo; con trafo ya se dibujó arriba) ──────
    if interruptor and instalacion != "trafo":
        _u_breaker(ax, xc, y-3, INK, 1.0)
        ax.text(xc-4, y-3, f"Interruptor\n{interruptor}",
                ha="right", va="center", fontsize=8, color=INK, fontweight="bold")
        vline(y, y-7); y -= 7
    else:
        vline(y, y-5); y -= 5

    # ── CARGA ─────────────────────────────────────────────────────────────────
    ax.add_patch(Polygon([[xc-4.5,y],[xc+4.5,y],[xc,y-8]],
                 closed=True, fill=False, ec=INK, lw=2.2))
    ax.text(xc, y-10, "CARGA",
            ha="center", va="top", fontsize=10, fontweight="bold", color=INK)

    # ── Plano de simbologia (panel derecho) ────────────────────────────────────
    px0, px1 = 75, 132
    py0, py1 = 5, 90
    ax.add_patch(FancyBboxPatch((px0, py0), px1-px0, py1-py0,
                 boxstyle="round,pad=0.6,rounding_size=2",
                 fill=False, ec="#2B2B2B", lw=1.4))
    ax.text((px0+px1)/2, py1-3, "PLANO DE SIMBOLOGIA",
            ha="center", fontsize=10, fontweight="bold", color=INK)
    ax.text((px0+px1)/2, py1-6.5, "IEC / UNE 60617",
            ha="center", fontsize=7.5, color="#888", style="italic")

    sym_items = [
        ("Transformador de potencia",      lambda x,y: _u_xfmr(ax,x,y,INK,0.72)),
        ("Transformador de corriente (TC)",lambda x,y: _u_ct(ax,x,y,COL["R"],0.82)),
        ("Transformador de tension (TP)",  lambda x,y: _u_vt(ax,x,y,COL["S"],0.82,False)),
        ("Interruptor automatico",         lambda x,y: _u_breaker(ax,x,y,INK,0.82)),
        ("Seccionador",                    lambda x,y: _u_disc(ax,x,y,INK,0.82)),
        ("Bloque de prueba",               lambda x,y: ax.add_patch(
            Rectangle((x-3,y-1.8),6,3.6,fill=True,fc="#E8EFF7",ec="#444",lw=1.0))),
        ("Medidor de energia (kWh)",       lambda x,y: ax.add_patch(
            Rectangle((x-3,y-1.8),6,3.6,fill=True,fc=INK,ec=INK))),
        ("Barra / barraje",                lambda x,y: ax.plot([x-3.5,x+3.5],[y,y],color=INK,lw=3.5)),
        ("Carga (general)",                lambda x,y: ax.add_patch(
            Polygon([[x-2,y+2],[x+2,y+2],[x,y-2]],closed=True,fill=False,ec=INK,lw=1.6))),
    ]
    sx = px0+8; tx = px0+16
    item_ys = np.linspace(py1-11, py0+6, len(sym_items))
    for (lbl, draw_sym), yy in zip(sym_items, item_ys):
        draw_sym(sx, yy)
        ax.text(tx, yy, lbl, ha="left", va="center", fontsize=8, color=INK)

    plt.savefig(out_path, dpi=160, bbox_inches="tight",
                facecolor="white", pad_inches=0.3)
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
    print("OK todas")
