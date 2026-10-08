#!/usr/bin/env python3
"""Plano de GABINETE COMPARTIDO (medida directa con otros usuarios) de punta a punta.

Caso real que lo motivo: el usuario describio por el dialogo IA "medida directa, MT 13,2 kV,
transformador interno en subestacion, gabinete interior compartido con 4 medidores mas,
totalizador posterior al medidor, 220 V" y el bot devolvio solo "barraje 220 V -> medidor -> carga";
luego escribio "no mostro el cuadro de lo compartido con 4 mas" y esa correccion cayo en la consulta
normativa (timeout de Gemini). Cubre:
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
    prueba_dibujo()
    prueba_despacho()
    prueba_parser()
    prueba_completar()
    prueba_coherencia()
    asyncio.run(prueba_dialogo())
    prueba_deteccion()
    asyncio.run(prueba_correccion())
    print("\nFALLOS:", MALOS)
    sys.exit(1 if MALOS else 0)

if __name__ == "__main__":
    main()
