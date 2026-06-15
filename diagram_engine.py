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
      - B3 bloque -> B1 medidor CHEQUEO  (cable externo, se maneja en ruteo)
      - borne 4 CHEQUEO -> borne 6 PRINCIPAL (cable externo, se maneja en ruteo)
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
    if respaldo: titulo+="   ·   PRINCIPAL + CHEQUEO"
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
                draw_meter(132,162,10,10+h,"CHEQUEO")]

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
    Medida DIRECTA — Simetrica o Asimetrica.

    SIMETRICA:  El tap de tension se toma en el lado de la ACOMETIDA (antes de
                la bobina I). Puente externo entre T_in y V+. La bobina V mide
                la tension de la linea de suministro.

    ASIMETRICA: El tap de tension se toma en el lado de la CARGA (despues de
                la bobina I). Puente externo entre T_out y V+. La bobina V mide
                la tension en bornes de carga.

    Layout por fase (4 terminales en bornera):
      Simetrica : [I_in | V+  | V-  | I_out]  — puente I_in <-> V+  (izquierda)
      Asimetrica: [I_in | I_out | V+ | V- ]   — puente I_out <-> V+ (derecha)
    """
    sistema  = cfg.get("sistema", "tri4h")
    norma    = cfg.get("norma",   "RA8")
    conexion = cfg.get("conexion","simetrica")
    respaldo = bool(cfg.get("respaldo", False))

    all_ph  = phases_of(sistema)
    n_ph    = len(all_ph)
    sis_lbl = {"mono":"MONOFASICA","bifasico":"BIFASICA",
               "tri3h":"TRIFASICA 3 HILOS","tri4h":"TRIFASICA 4 HILOS"}[sistema]

    # ── Canvas ─────────────────────────────────────────────────────────────
    BLOCK_W  = 44          # ancho del bloque de 4 terminales por fase
    MARGIN_H = 16          # margen horizontal total (8 cada lado)
    W        = n_ph * BLOCK_W + MARGIN_H + 60   # extra para labels
    W        = max(W, 140)

    HDR = 9    # cabecera
    MB  = 34   # altura interior del medidor (coils + bornera)
    PH  = 5.5  # separacion vertical entre lineas de fase
    FTR = 12   # neutro + notas
    H   = HDR + MB + n_ph * PH + FTR
    H   = max(H, 65)

    fig, ax = plt.subplots(figsize=(W / 11, H / 8.5))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    # ── Titulos ────────────────────────────────────────────────────────────
    ax.text(W/2, H-1.5,
            f"DIAGRAMA DE CONEXIONES  ·  MEDIDA DIRECTA  ·  {sis_lbl}",
            ha="center", fontsize=10, fontweight="bold", color=INK)
    sub = f"Norma {norma}  ·  Conexion {conexion.upper()}"
    if respaldo: sub += "  ·  PRINCIPAL + CHEQUEO"
    ax.text(W/2, H-3.3, sub, ha="center", fontsize=8.5, color="#666")

    # ── Zonas horizontales ─────────────────────────────────────────────────
    # [0 .. XSL]       supply label
    # [XSL .. XML]     conductores de acometida
    # [XML .. XMR]     caja MEDIDOR
    # [XMR .. XLL]     conductores de carga
    # [XLL .. W]       carga label
    XSL = 2        # supply label x
    XML = 30       # medidor borde izquierdo
    XMR = W - 30   # medidor borde derecho
    XLL = W - 2    # load label x
    X_SACOM = 18   # x donde la acometida entra a la zona del medidor
    X_CARGA = W - 18

    # ── Y referencias ──────────────────────────────────────────────────────
    BOX_TOP = H - HDR
    BOX_BOT = BOX_TOP - MB

    # Bornera: franja inferior del medidor
    TB_H   = 7.5
    TB_Y0  = BOX_BOT
    TB_Y1  = TB_Y0 + TB_H
    TERM_Y = (TB_Y0 + TB_Y1) / 2

    # Lineas de fase (debajo de la bornera)
    PH_YS  = [BOX_BOT - PH * (i + 1) for i in range(n_ph)]

    # Linea de neutro
    Y_N = PH_YS[-1] - PH - 2.5

    # ── Caja MEDIDOR ────────────────────────────────────────────────────────
    ax.add_patch(Rectangle(
        (XML, BOX_BOT - 0.5), XMR - XML, BOX_TOP - BOX_BOT + 0.5,
        fill=False, ec="#444", lw=1.5, ls=(0,(4,3)), zorder=1
    ))
    ax.text((XML+XMR)/2, BOX_TOP + 1.8, "MEDIDOR",
            ha="center", va="bottom", fontsize=9, fontweight="bold", color="#333")

    # ── Bornera ─────────────────────────────────────────────────────────────
    ax.add_patch(Rectangle(
        (XML+4, TB_Y0), XMR-XML-8, TB_H,
        fill=True, fc="#F0F0F0", ec="#555", lw=1.0, zorder=2
    ))
    ax.text((XML+XMR)/2, TB_Y0 - 1.2, "BORNERA",
            ha="center", va="top", fontsize=7, color="#999")

    # ── Terminales: 4 por fase ──────────────────────────────────────────────
    TR       = 1.5   # radio terminal
    bornera_w = XMR - XML - 8
    block_w   = bornera_w / n_ph

    ph_terms = []    # [(ta, tb, tc, td), ...] por fase
    for pi in range(n_ph):
        bx = XML + 4 + pi * block_w
        sp = block_w / 5.0
        ta = bx + sp * 1
        tb = bx + sp * 2
        tc = bx + sp * 3
        td = bx + sp * 4
        ph_terms.append((ta, tb, tc, td))

    # Dibujar circulos de terminal y etiquetas
    # Labels correctos segun norma colombiana (RETIE):
    #   Simetrica : [1:F_ent | 2:N_sal | 3:N_ent | 4:F_sal]  ← patron ESPEJO
    #   Asimetrica: [1:F_ent | 2:F_sal | 3:N_ent | 4:N_sal]  ← patron SECUENCIAL
    for pi, ph in enumerate(all_ph):
        ta, tb, tc, td = ph_terms[pi]
        for tx in (ta, tb, tc, td):
            ax.add_patch(Circle((tx, TERM_Y), TR,
                         fill=True, fc="white", ec="#333", lw=1.4, zorder=5))
        if conexion == "simetrica":
            lbls = ["1-Fent", "2-Nsal", "3-Nent", "4-Fsal"]
        else:
            lbls = ["1-Fent", "2-Fsal", "3-Nent", "4-Nsal"]
        for tx, lbl in zip((ta, tb, tc, td), lbls):
            ax.text(tx, TB_Y0 - 0.4, lbl, ha="center", va="top",
                    fontsize=5.5, color="#666")

    # ── Bobinas y cableado interno ──────────────────────────────────────────
    CZ_BOT = TB_Y1 + 1.5
    CZ_TOP = BOX_TOP - 1.0
    CZ_H   = CZ_TOP - CZ_BOT

    I_CY   = CZ_BOT + CZ_H * 0.72
    V_CY   = CZ_BOT + CZ_H * 0.28
    COIL_H = min(CZ_H * 0.35, 7)

    for pi, ph in enumerate(all_ph):
        c  = COL[ph]
        ta, tb, tc, td = ph_terms[pi]

        # ── Asignacion de terminales (norma colombiana RETIE) ───────────
        if conexion == "simetrica":
            # Bornera: [1:F_ent | 2:N_sal | 3:N_ent | 4:F_sal]
            # La fase entra por borne 1 y sale por borne 4 (patron espejo/cruzado).
            # El neutro entra por borne 3 y sale por borne 2.
            # Tap de tension V+ en borne 1 (lado acometida).
            T_fin  = ta   # borne 1: Fase entrada
            T_nout = tb   # borne 2: Neutro salida (hacia carga)
            T_nin  = tc   # borne 3: Neutro entrada (de la red)
            T_fout = td   # borne 4: Fase salida
            T_vpos = ta   # V+ tap: mismo borne que Fase entrada
            T_vneg = tc   # V- ref: Neutro entrada
        else:
            # Bornera: [1:F_ent | 2:F_sal | 3:N_ent | 4:N_sal]
            # La fase entra por borne 1 y sale por borne 2 (contiguos).
            # El neutro entra por borne 3 y sale por borne 4 (contiguos).
            # Tap de tension V+ en borne 2 (lado carga).
            T_fin  = ta   # borne 1: Fase entrada
            T_fout = tb   # borne 2: Fase salida
            T_nin  = tc   # borne 3: Neutro entrada (de la red)
            T_nout = td   # borne 4: Neutro salida (hacia carga)
            T_vpos = tb   # V+ tap: mismo borne que Fase salida
            T_vneg = tc   # V- ref: Neutro entrada

        # ── Bobina I (serie, camino de corriente): T_fin → T_fout ──────
        icx   = (T_fin + T_fout) / 2
        ic_w  = max(abs(T_fout - T_fin) - 2, 8)
        ic_x0 = icx - ic_w / 2
        ic_x1 = icx + ic_w / 2
        ic_y0 = I_CY - COIL_H / 2
        ax.add_patch(Rectangle((ic_x0, ic_y0), ic_w, COIL_H,
                     fill=True, fc="#FFFDE7", ec=c, lw=1.3, zorder=3))
        ax.text(icx, I_CY, "I", ha="center", va="center",
                fontsize=8, fontweight="bold", color=c, zorder=4)

        # ── Bobina V (paralelo, medida de tension) ──────────────────────
        # V+ toma del mismo borne que la fase (T_vpos = T_fin o T_fout).
        # V- referencia al neutro (T_vneg = T_nin).
        vcx   = (T_vpos + T_vneg) / 2
        vc_w  = max(abs(T_vneg - T_vpos) - 2, 8)
        vc_x0 = vcx - vc_w / 2
        vc_x1 = vcx + vc_w / 2
        vc_y0 = V_CY - COIL_H / 2
        ax.add_patch(Rectangle((vc_x0, vc_y0), vc_w, COIL_H,
                     fill=True, fc="#E3F2FD", ec=c, lw=1.3, ls=(0,(3,2)), zorder=3))
        ax.text(vcx, V_CY, "V", ha="center", va="center",
                fontsize=8, fontweight="bold", color=c, zorder=4)

        # ── Cableado interno: terminales → bobinas ──────────────────────
        def _wire_up(tx, ex, ey, col, lw=1.4):
            ax.plot([tx, tx], [TERM_Y + TR, ey], color=col, lw=lw, zorder=2)
            ax.plot([tx, ex], [ey, ey], color=col, lw=lw, zorder=2)

        # Fase → I_coil (serie)
        _wire_up(T_fin,  ic_x0, ic_y0, c)
        _wire_up(T_fout, ic_x1, ic_y0, c)

        # V+ tap: desde T_vpos (mismo hilo de fase) → V_coil lado V+
        # Nodo de union en el hilo de fase a la altura de la bobina V
        vc_vplus_edge = vc_x0 if T_vpos <= vcx else vc_x1
        _wire_up(T_vpos, vc_vplus_edge, vc_y0, c, lw=1.2)
        # Punto de nodo (●) sobre el hilo de fase en vc_y0
        ax.add_patch(Circle((T_vpos, vc_y0), 1.0, fc=c, ec=c, zorder=6))

        # Neutro pass-through interno: T_nin ──── T_nout (con cruce en simetrica)
        N_PASS_Y = vc_y0 - 2.2
        ax.plot([T_nin,  T_nin],  [TERM_Y + TR, N_PASS_Y], color=COL["N"], lw=1.2, zorder=2)
        ax.plot([T_nin,  T_nout], [N_PASS_Y,    N_PASS_Y], color=COL["N"], lw=1.2, zorder=2)
        ax.plot([T_nout, T_nout], [N_PASS_Y, TERM_Y + TR], color=COL["N"], lw=1.2, zorder=2)

        # V- referencia: nodo en el hilo de neutro interno → V_coil lado V-
        vc_vminus_edge = vc_x1 if T_vpos <= T_vneg else vc_x0
        ax.add_patch(Circle((T_nin, N_PASS_Y), 1.0, fc=COL["N"], ec=COL["N"], zorder=6))
        ax.plot([T_nin, T_nin],         [N_PASS_Y, vc_y0],         color=COL["N"], lw=1.2, ls=(0,(3,2)), zorder=2)
        ax.plot([T_nin, vc_vminus_edge], [vc_y0,   vc_y0],         color=COL["N"], lw=1.2, ls=(0,(3,2)), zorder=2)

        # ── Conductores externos: fase ──────────────────────────────────
        py = PH_YS[pi]
        ax.plot([X_SACOM, T_fin],   [py, py], color=c, lw=2.5, zorder=2)
        ax.plot([T_fin,   T_fin],   [py, TERM_Y - TR], color=c, lw=2.5, zorder=2)
        ax.plot([T_fout,  T_fout],  [TERM_Y - TR, py], color=c, lw=2.5, zorder=2)
        ax.plot([T_fout,  X_CARGA], [py, py], color=c, lw=2.5, zorder=2)

        # ── Conductores externos: neutro (ramas a T_nin y T_nout) ───────
        ax.plot([T_nin,  T_nin],  [Y_N, TERM_Y - TR], color=COL["N"], lw=1.8, ls=(0,(5,2)), zorder=2)
        ax.plot([T_nout, T_nout], [Y_N, TERM_Y - TR], color=COL["N"], lw=1.8, ls=(0,(5,2)), zorder=2)

        # ── Etiquetas de fase ───────────────────────────────────────────
        ax.text(XSL + 0.5, py, f"Fase {ph}", ha="left",  va="center",
                fontsize=9, fontweight="bold", color=c)
        ax.text(XLL - 0.5, py, f"Fase {ph}", ha="right", va="center",
                fontsize=9, fontweight="bold", color=c)

    # ── Bus de neutro ───────────────────────────────────────────────────────
    ax.plot([X_SACOM, X_CARGA], [Y_N, Y_N],
            color=COL["N"], lw=2.0, ls=(0,(6,3)), zorder=2)
    ax.text(XSL + 0.5, Y_N, "Neutro", ha="left",  va="center",
            fontsize=9, fontweight="bold", color=COL["N"])
    ax.text(XLL - 0.5, Y_N, "Neutro", ha="right", va="center",
            fontsize=9, fontweight="bold", color=COL["N"])

    # ── Buses verticales de acometida y carga ───────────────────────────────
    bus_top = PH_YS[0] + 1.5
    bus_bot = Y_N
    ax.plot([X_SACOM, X_SACOM], [bus_bot, bus_top], color="#AAA", lw=0.8, zorder=1)
    ax.plot([X_CARGA, X_CARGA], [bus_bot, bus_top], color="#AAA", lw=0.8, zorder=1)
    ax.text(X_SACOM - 1, (bus_top + bus_bot) / 2, "ACOMETIDA",
            ha="right", va="center", fontsize=7.5, fontweight="bold",
            color="#555", rotation=90)
    ax.text(X_CARGA + 1, (bus_top + bus_bot) / 2, "CARGA",
            ha="left", va="center", fontsize=7.5, fontweight="bold",
            color="#555", rotation=90)

    # ── Nota explicativa — patron de bornera segun sistema ──────────────────
    if sistema == "mono":
        if conexion == "simetrica":
            nota = "Bornera: [1:F-ent | 2:N-sal | 3:N-ent | 4:F-sal]  ·  ESPEJO — neutro en el CENTRO"
        else:
            nota = "Bornera: [1:F-ent | 2:F-sal | 3:N-ent | 4:N-sal]  ·  SECUENCIAL — neutro al FINAL"
    elif sistema == "bifasico":
        if conexion == "simetrica":
            nota = "Bornera: [1:R-ent | 2:N-sal | 3:N-ent | 4:R-sal | 5:S-ent | 6:S-sal]  ·  ESPEJO"
        else:
            nota = "Bornera: [1:R-ent | 2:R-sal | 3:S-ent | 4:S-sal | 5:N-ent | 6:N-sal]  ·  SECUENCIAL"
    elif sistema == "tri4h":
        if conexion == "simetrica":
            nota = ("Bornera 8 bornes: [1:R-ent | 2:S-ent | 3:T-ent | 4:N-ent | 5:N-sal | 6:T-sal | 7:S-sal | 8:R-sal]"
                    "  ·  ESPEJO — neutro en el CENTRO (bornes 4-5)")
        else:
            nota = ("Bornera 8 bornes: [1:R-ent | 2:R-sal | 3:S-ent | 4:S-sal | 5:T-ent | 6:T-sal | 7:N-ent | 8:N-sal]"
                    "  ·  SECUENCIAL — neutro al FINAL (bornes 7-8)")
    else:  # tri3h Aron
        nota = "Bornera Aron: [1:R-ent | 2:R-sal | 3:S-ref | 4:S-ref | 5:T-ent | 6:T-sal]  ·  2 elementos"
    ax.text(W/2, Y_N - 2.5, nota, ha="center", va="top",
            fontsize=6.5, color="#444", style="italic")

    # Notas de instalacion
    notas = []
    if cfg.get("instalacion") == "trafo" and cfg.get("trafo_kva"):
        notas.append(f"Trafo {cfg.get('trafo_uso','')} {cfg['trafo_kva']} kVA".strip())
    elif cfg.get("instalacion") == "barraje":
        notas.append("Barraje BT")
    if cfg.get("interruptor"):
        notas.append(f"Interruptor {cfg['interruptor']}")
    if notas:
        ax.text(W/2, Y_N - 5.5, "  ·  ".join(notas),
                ha="center", va="top", fontsize=7.5, color="#555")

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

    # Canvas: más ancho para Aron con respaldo, más alto con respaldo
    fig_w = 22 if (respaldo and sistema == "tri3h") else 18
    fig_h = 22 if respaldo else 11
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    xlim  = 210 if (respaldo and sistema == "tri3h") else 190
    ylim  = 240 if respaldo else 116
    ax.set_xlim(0, xlim); ax.set_ylim(0, ylim); ax.axis("off")

    titulo = f"DIAGRAMA DE CONEXIONES   ·   MEDIDA {tipo.upper()}   ·   {SIS_TXT[sistema]}"
    if respaldo: titulo += "   ·   PRINCIPAL + CHEQUEO"
    ty_titulo = 236 if respaldo else 112
    ty_sub    = 231 if respaldo else 107.5
    ax.text(95, ty_titulo, titulo, ha="center", va="center", fontsize=15, fontweight="bold", color=INK)
    sub = f"Norma {norma}"
    if rel_tc: sub += f"      RTC {rel_tc}"
    if rel_tp: sub += f"      RTP {rel_tp}"
    if cfg.get("calibre_acometida"): sub += f"      Acometida {cfg['calibre_acometida']}"
    if cfg.get("seccionamiento") or cfg.get("interruptor"):
        amp = cfg.get("interruptor") or cfg.get("tc_amp","")
        if amp: sub += f"      Seccionador {amp}" + ("" if "A" in str(amp) else " A")
    ax.text(95, ty_sub, sub, ha="center", va="center", fontsize=10.5, color="#666")

    # ---------- PRIMARIO (ACOMETIDA) ----------
    base_y = 226 if respaldo else 104
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
    by1 = 226 if respaldo else 98
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

    def draw_meter(mx0, mx1, y_top, etq):
        """
        y_top: Y de la parte superior del área de bornes del medidor.
        Los bornes se espacian igual que el bloque (step).
        """
        n_m = len(meter_order)
        # Y de cada borne del medidor en orden físico, de arriba a abajo
        ys_m = np.array([y_top - i*step for i in range(n_m)])
        my0 = ys_m[-1] - step*0.5
        my1 = y_top    + step*0.5 + 14
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
    if not respaldo:
        m_y0, mxr0 = draw_meter(132, 164, meter_top, "MEDIDOR")
        draw_meter_bridges(m_y0, mxr0)
        meters = [(m_y0, mxr0)]
    else:
        n_m     = len(meter_order)
        meter_h = n_m * step + 18
        gap     = step * 2
        top_princ = meter_top
        top_cheq  = top_princ - meter_h - gap
        mx0 = 136 if sistema == "tri3h" else 132
        mx1 = mx0 + 32
        m_yp, mxrp = draw_meter(mx0, mx1, top_princ, "PRINCIPAL")
        m_yc, mxrc = draw_meter(mx0, mx1, top_cheq,  "CHEQUEO")
        draw_meter_bridges(m_yp, mxrp)
        draw_meter_bridges(m_yc, mxrc)
        meters = [(m_yp, mxrp), (m_yc, mxrc)]

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
    xm_cols = np.linspace(106, 128, len(order))
    xm_map  = {tlbl: xm_cols[i] for i,tlbl in enumerate(order)}

    for mi, (m_y, mxr) in enumerate(meters):
        for tlbl in order:
            if tlbl not in m_y or tlbl not in row:
                continue
            # tri3h: borne 3 (C1) va al borne 4 via cable especial, no directo
            if sistema == "tri3h" and tlbl == "3":
                continue
            yb = row[tlbl][0]   # Y en el bloque
            ym = m_y[tlbl]      # Y en el medidor (orden físico)
            ph = row[tlbl][1]; c = COL[ph]
            ls = (0,(6,3)) if ph=="N" else "-"
            lw = 1.7
            xm = xm_map[tlbl]
            ax.plot([xR, xm],[yb, yb], color=c, lw=lw, ls=ls)   # horizontal desde bloque
            ax.plot([xm, xm],[yb, ym], color=c, lw=lw, ls=ls)   # vertical
            ax.plot([xm, mxr],[ym, ym], color=c, lw=lw, ls=ls)  # horizontal al medidor

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
    cx0 = 164
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
    DIRECTA / SEMIDIRECTA (con barraje):
        RED -> [TC/TP si semidirecta] -> Medidor -> Interruptor -> CARGA

    DIRECTA / SEMIDIRECTA (con transformador):
        RED -> Transformador(es) -> [TC si semidirecta] -> Medidor -> Interruptor -> CARGA

    INDIRECTA (siempre con transformador despues de la medida):
        RED (MT) -> TC+TP (MT) -> Transformador(es) -> Medidor -> Interruptor -> CARGA
        (TC y TP se ubican en MEDIA TENSION, antes del/los transformador(es); no se dibuja barraje BT)
    """
    tipo      = cfg.get("tipo", "directa")
    sistema   = cfg.get("sistema", "tri4h")
    norma     = cfg.get("norma", "RA8")
    rel_tc    = cfg.get("rel_tc", "")
    rel_tp    = cfg.get("rel_tp", "")
    instalacion = cfg.get("instalacion", "barraje")

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_xlim(0, 100); ax.set_ylim(0, 85)
    ax.set_aspect("equal"); ax.axis("off")

    ax.text(50, 82, "DIAGRAMA UNIFILAR DE MEDIDA", ha="center", fontsize=14,
            fontweight="bold", color=INK)
    sub = f"Medida {tipo} · {SIS_TXT[sistema].split(' (')[0].title()} · Norma {norma}"
    ax.text(50, 78.5, sub, ha="center", fontsize=9.5, color="#666")

    xc = 32
    def vline(y1, y2, lw=2.6): ax.plot([xc, xc], [y1, y2], color=INK, lw=lw, zorder=2)
    def busbar(yy, label, extra=""):
        ax.plot([xc-13, xc+13], [yy, yy], color=INK, lw=4.5, zorder=2)
        ax.text(xc-15, yy, label, ha="right", va="center", fontsize=9.5, fontweight="bold", color=INK)
        if extra: ax.text(xc+15, yy, extra, ha="left", va="center", fontsize=8, color="#777")

    y = 70
    red_label = "RED (M.T.)" if tipo == "indirecta" else "RED"
    busbar(y, red_label, "")
    top = y
    y -= 4; vline(top, y)

    # ============================================================
    # INDIRECTA: TC y TP se ubican en MT, ANTES del transformador
    # ============================================================
    if tipo == "indirecta":
        nodo = y
        ax.add_patch(Circle((xc, nodo), 0.8, fc=INK, ec=INK, zorder=4))

        # Seccionador ANTES de TC/TP (si aplica)
        sec_pos = cfg.get("sec_pos", "")  # "antes" | "despues" | ""
        if sec_pos == "antes":
            _u_disc(ax, xc, nodo-2.5, INK, 0.9)
            ax.text(xc+4, nodo-2.5, "Seccionador\n(antes TC/TP)",
                    ha="left", va="center", fontsize=7.5, color=INK, fontweight="bold")
            y = nodo - 5; vline(nodo, y); nodo = y
            ax.add_patch(Circle((xc, nodo), 0.8, fc=INK, ec=INK, zorder=4))

        # TC en serie en MT (justo bajo la red / bajo el seccionador)
        _u_ct(ax, xc, nodo-3.5, COL["R"], 0.85)
        ax.text(xc+4, nodo-3.5, f"TC (MT)\n{rel_tc or '—'}", ha="left", va="center",
                fontsize=8, color=COL["R"], fontweight="bold")

        # TP en paralelo, tomado mas abajo
        tpx = xc - 13
        tpy = nodo - 9
        ax.plot([xc, xc], [nodo-6, tpy], color=COL["S"], lw=1.6)
        ax.plot([xc, tpx], [tpy, tpy], color=COL["S"], lw=1.6)
        _u_vt(ax, tpx, tpy-2.3, COL["S"], 0.85, ground=True)
        ax.text(tpx-2.2, tpy, f"TP (MT)\n{rel_tp or '—'}", ha="right", va="center",
                fontsize=7.5, color=COL["S"], fontweight="bold")

        y = nodo - 9.5
        vline(nodo, y)

        # Seccionador DESPUES de TC/TP (si aplica)
        if sec_pos == "despues":
            _u_disc(ax, xc, y-2.5, INK, 0.9)
            ax.text(xc+4, y-2.5, "Seccionador\n(después TC/TP)",
                    ha="left", va="center", fontsize=7.5, color=INK, fontweight="bold")
            y2 = y - 5; vline(y, y2); y = y2

        # Medidor a la izquierda, debajo del nivel del TP, con señales desde TC y TP en MT
        my = tpy - 7
        _u_meter(ax, 2, my, 18, 9)
        ax.annotate("", xy=(20, my+1.2), xytext=(xc-1.2, nodo-3.5),
                     arrowprops=dict(arrowstyle="-|>", color=COL["R"], ls=":", lw=1.3))
        ax.annotate("", xy=(20, my-1.2), xytext=(tpx, tpy-1.0),
                     arrowprops=dict(arrowstyle="-|>", color=COL["S"], ls=":", lw=1.3))
        ax.text(11, my-6.5, "señales de\nmedida (I, V)", ha="center", va="top", fontsize=7, color="#888", style="italic")

    # ============================================================
    # Transformador(es) - DESPUES de TC/TP en indirecta;
    # primer elemento si es directa/semidirecta con instalacion=trafo
    # SEMIDIRECTA: seccionador SIEMPRE antes del trafo (fijo, sin preguntar)
    # ============================================================
    if instalacion == "trafo":
        # Seccionador fijo antes del trafo para semidirecta
        if tipo == "semidirecta":
            _u_disc(ax, xc, y-2.5, INK, 0.9)
            ax.text(xc+4, y-2.5, "Seccionador",
                    ha="left", va="center", fontsize=7.5, color=INK, fontweight="bold")
            y2 = y - 5; vline(y, y2); y = y2
        kva   = cfg.get("trafo_kva", "")
        ttipo = cfg.get("trafo_tipo", "trifasico")
        uso   = cfg.get("trafo_uso", "")
        n_tr  = int(cfg.get("n_trafos", 1) or 1)
        lista_kva = cfg.get("trafo_kva_lista", [kva] if kva else [])

        if n_tr > 1 and lista_kva:
            ax.text(xc+10, y+1.2, f"{n_tr} Transformadores\nen paralelo", ha="left", fontsize=7.5, color="#666")
            spread = 8
            xs = [xc + (i-(n_tr-1)/2)*spread for i in range(n_tr)]
            for x, kv in zip(xs, lista_kva):
                ax.plot([xc, x], [y, y-1.5], color=INK, lw=1.4)
                _u_xfmr(ax, x, y-5, INK, 0.9)
                ax.text(x, y-9, f"{kv} kVA", ha="center", fontsize=7.5, color=INK, fontweight="bold")
                ax.plot([x, xc], [y-8, y-10.5], color=INK, lw=1.4)
            y -= 11.5
            vline(y+1, y)
        else:
            _u_xfmr(ax, xc, y-3.5, INK, 1.2)
            txt_uso = f" ({uso})" if uso else ""
            etiqueta = f"Trafo {ttipo}{txt_uso}"
            if kva: etiqueta += f"\n{kva} kVA"
            ax.text(xc+6, y-3.5, etiqueta, ha="left", va="center", fontsize=8, color=INK, fontweight="bold")
            y -= 7
            vline(y+3.5, y)
    elif tipo != "indirecta":
        ax.text(xc+4, y+1.5, "Conectado a barraje\n(sin transformador)", ha="left", va="center", fontsize=8, color="#666")

    # ============================================================
    # DIRECTA/SEMIDIRECTA: TC/TP van aqui (en BT, despues del trafo o barraje)
    # ============================================================
    if tipo != "indirecta":
        nodo = y
        ax.add_patch(Circle((xc, nodo), 0.8, fc=INK, ec=INK, zorder=4))

        if tipo == "semidirecta":
            tc_label = rel_tc or (f"{cfg.get('tc_amp','—')} A" if cfg.get("tc_amp") else "—")
            _u_ct(ax, xc, nodo-4.5, COL["R"], 0.9)
            ax.text(xc+4, nodo-4.5, f"TC\n{tc_label}", ha="left", va="center",
                    fontsize=8, color=COL["R"], fontweight="bold")
            y2 = nodo - 8
        else:
            y2 = nodo - 3.5
        vline(nodo, y2)
        y = y2

        my = nodo - 4.5
        _u_meter(ax, 3, my, 20, 10)
        ax.annotate("", xy=(23, my+1.3), xytext=(xc-1.2, nodo-4.5),
                     arrowprops=dict(arrowstyle="-|>", color=COL["R"], ls=":", lw=1.3))
        ax.text(13, my-7, "señales de\nmedida (I)" if tipo=="semidirecta" else "medida\ndirecta",
                ha="center", va="top", fontsize=7, color="#888", style="italic")

    tc_pos = cfg.get("tc_pos")

    # ============================================================
    # UN SOLO elemento de proteccion: interruptor (si existe) o
    # info de TC-antes-del-totalizador (semidirecta+barraje sin interruptor)
    # ============================================================
    interruptor = cfg.get("interruptor")
    interruptor_pos = cfg.get("interruptor_pos")
    seccionamiento = cfg.get("seccionamiento")

    proteccion_amp = interruptor or (f"{cfg.get('tc_amp')} A" if (tc_pos and cfg.get("tc_amp")) else None)

    if proteccion_amp:
        _u_breaker(ax, xc, y-2.5, INK, 0.9)
        pos_txt = ""
        if interruptor_pos:
            pos_txt = f"\n({interruptor_pos} del medidor)"
        elif tc_pos:
            pos_txt = f"\n(TC {tc_pos} del totalizador)"
        ax.text(xc+5, y-2.5, f"Interruptor {proteccion_amp}{pos_txt}",
                ha="left", va="center", fontsize=8, color=INK, fontweight="bold")
        y -= 5; vline(y+5, y)
    else:
        y -= 4; vline(y+4, y)

    # Seccionador adicional SOLO si no se dibujo ya ningun elemento de proteccion
    if seccionamiento and not proteccion_amp:
        _u_disc(ax, xc, y-2.5, INK, 0.9)
        ax.text(xc+5, y-2.5, "Seccionador", ha="left", va="center", fontsize=8, color=INK, fontweight="bold")
        y -= 5; vline(y+5, y)

    # ---- Carga ----
    ax.add_patch(Polygon([[xc-3.5,y],[xc+3.5,y],[xc,y-6]], closed=True, fill=False, ec=INK, lw=2))
    ax.text(xc, y-8, "CARGA", ha="center", va="top", fontsize=9, fontweight="bold", color=INK)

    # ---------------- PLANO DE SIMBOLOGIA ----------------
    px0, px1 = 68, 98
    py1 = 67; py0 = 8
    ax.add_patch(FancyBboxPatch((px0,py0),px1-px0,py1-py0,boxstyle="round,pad=0.6,rounding_size=2",
                 fill=False, ec="#2B2B2B", lw=1.4))
    ax.text((px0+px1)/2, py1-2.8, "PLANO DE SIMBOLOGIA", ha="center", fontsize=9.5, fontweight="bold", color=INK)
    ax.text((px0+px1)/2, py1-5.3, "IEC / UNE 60617", ha="center", fontsize=7, color="#888", style="italic")

    items = [
        ("Transformador de potencia", lambda x,y: _u_xfmr(ax,x,y,INK,0.7)),
        ("Transformador de corriente (TC)", lambda x,y: _u_ct(ax,x,y,COL["R"],0.8)),
        ("Transformador de tension (TP)", lambda x,y: _u_vt(ax,x,y,COL["S"],0.8,False)),
        ("Interruptor automatico", lambda x,y: _u_breaker(ax,x,y,INK,0.8)),
        ("Seccionador", lambda x,y: _u_disc(ax,x,y,INK,0.8)),
        ("Medidor de energia", lambda x,y: (ax.add_patch(Rectangle((x-2.5,y-1.7),5,3.4,fill=True,fc=INK,ec=INK)))),
        ("Barra / barraje", lambda x,y: ax.plot([x-3,x+3],[y,y],color=INK,lw=3.5)),
        ("Carga", lambda x,y: ax.add_patch(Polygon([[x-2,y+1.8],[x+2,y+1.8],[x,y-1.8]],closed=True,fill=False,ec=INK,lw=1.6))),
    ]
    sx = px0+7; tx = px0+13
    ys2 = np.linspace(py1-9, py0+4, len(items))
    for (label,dsym), yy in zip(items, ys2):
        dsym(sx, yy)
        ax.text(tx, yy, label, ha="left", va="center", fontsize=8, color=INK)

    plt.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white", pad_inches=0.3)
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
