#!/usr/bin/env python3
"""Recorre el menu de botones REAL (on_button/on_text de bot.py, con objetos
de Telegram simulados) por todas las combinaciones tipo x salida y verifica
que NINGUN camino quede sin respuesta ("callejon sin salida").

Motivo: un cambio de botones a texto libre (n_trafos) dejo dos pantallas
mostrando botones sin handler -- Indirecta + "Cx + Uni" nunca generaba nada
y ningun test lo detecto, porque test_menu_flow.py solo llama al motor.

  python test_menu_walk.py           # solo flujo (rapido, no dibuja)
  python test_menu_walk.py --draw    # ademas dibuja cada diagrama de verdad
"""
import sys, os, asyncio, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
logging.disable(logging.CRITICAL)
import bot

bot._genai_client = None   # fuerza el menu de botones (no el dialogo IA)
DRAW = "--draw" in sys.argv

if not DRAW:
    # Modo rapido: no dibuja, pero deja pasar _enviar_foto con una imagen falsa
    # (asi se sigue ejerciendo _verificar_coherencia y el envio de la foto).
    import tempfile
    def _generar_falso(cfg):
        cfg, notas = bot._verificar_coherencia(cfg)
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.write(b"x"); t.close()
        return [("Diagrama", t.name)], notas, cfg
    bot._generar = _generar_falso

# Respuesta de texto para cada paso del flujo que espera un valor escrito.
TEXTO = {"esperando_n_usuarios_compartido": "4", "esperando_n_trafos": "1",
         "esperando_kva": "150", "esperando_prot_amp": "100",
         "esperando_rel_tc": "200/5", "esperando_rel_tp": "13200/120",
         "esperando_prot_amp_ind": "100", "esperando_calibre": "AWG 2/0"}


class Msg:
    def __init__(self, ev): self.ev = ev
    async def reply_text(self, text, reply_markup=None, **kw): self.ev.append(("text", text, reply_markup))
    async def edit_message_text(self, text, reply_markup=None, **kw): self.ev.append(("text", text, reply_markup))
    async def edit_message_reply_markup(self, **kw): pass
    async def reply_chat_action(self, *a, **k): pass
    async def reply_photo(self, photo=None, caption=None, **kw): self.ev.append(("photo", caption, None))

class Query(Msg):
    def __init__(self, data, ev): super().__init__(ev); self.data = data; self.message = Msg(ev)
    async def answer(self, *a, **k): pass

class Upd:
    def __init__(self, ev, data=None, text=None):
        self.effective_user = None   # _access_ok() deja pasar si no hay usuario
        self.callback_query = Query(data, ev) if data is not None else None
        self.message = None if data is not None else Msg(ev)
        if self.message: self.message.text = text
        self.effective_message = self.callback_query.message if data is not None else self.message

class Ctx:
    def __init__(self): self.user_data = {}; self.bot = None


async def paso(ctx, ev, kind, arg):
    n0 = len(ev)
    if kind == "btn": await bot.on_button(Upd(ev, data=arg), ctx)
    else:             await bot.on_text(Upd(ev, text=arg), ctx)
    return ev[n0:]

def texto_pendiente(ctx):
    if ctx.user_data.get("kva_trafo_idx") is not None: return "150"
    return next((v for k, v in TEXTO.items() if ctx.user_data.get(k)), None)

async def reproducir(path):
    ctx, ev, last = Ctx(), [], []
    ctx.user_data["cfg"] = dict(bot.DEFAULT); ctx.user_data["paso_n"] = 1
    for kind, arg in path:
        last = await paso(ctx, ev, kind, arg)
    return ctx, ev, last

async def recorrer(tipo, salida):
    """DFS sobre todos los botones; devuelve [(estado, camino, detalle)]."""
    out, pila = [], [[("btn", "inicio:diagramas"), ("btn", f"tipo:{tipo}"), ("btn", f"salida:{salida}")]]
    while pila:
        path = pila.pop()
        ctx, ev, last = await reproducir(path)
        fotos = [e for e in ev if e[0] == "photo"]
        txts = [e[1] for e in ev if e[0] == "text"]
        if fotos:
            if salida == "unifilar" and not any(a.startswith("sistema:") for _, a in path):
                # Regresion: el menu llego a generar sin preguntar el sistema y
                # un monofasico salia rotulado "Trifasica 4 Hilos".
                out.append(("NO_PREGUNTA_SISTEMA", path, "genero sin pasar por sistema:*")); continue
            out.append(("OK", path, None)); continue
        if any("No pude generar" in t or "Error al generar" in t for t in txts):
            out.append(("ERROR_GENERAR", path, txts[-1])); continue
        if not last:
            out.append(("SIN_RESPUESTA", path, f"el bot no respondio a {path[-1]}")); continue
        t = texto_pendiente(ctx)
        if t is not None:
            pila.append(path + [("txt", t)]); continue
        botones = next(([b.callback_data for row in e[2].inline_keyboard for b in row] for e in reversed(last) if e[2]), [])
        if not botones:
            out.append(("ATASCADO", path, txts[-1][:100])); continue
        for b in botones:
            campo, val = b.split(":", 1)
            if campo == "generar" and val != "si": continue   # editar/reiniciar: otro sub-flujo
            # Botones de un toque y submenu Editar vuelven a la MISMA pantalla de
            # confirmacion: seguirlos es un ciclo infinito (el recorrido no deduplica
            # estados). Su comportamiento lo cubre test_menu_opciones.py.
            if campo in ("editval", "editcampo"): continue
            pila.append(path + [("btn", b)])
    return out

async def main():
    malos = 0
    for tipo in ("directa", "semidirecta", "indirecta"):
        for salida in ("conexiones", "unifilar", "ambos"):
            res = await recorrer(tipo, salida)
            fallos = [r for r in res if r[1] and r[0] != "OK"]
            malos += len(fallos)
            print(f"{tipo:12s} {salida:10s} {len(res)-len(fallos):4d} OK  {len(fallos)} con problema")
            for estado, path, det in fallos[:3]:
                print(f"     {estado}: {[a for _, a in path[3:]]} -> {det}")
    print("\nRESULTADO:", "TODO OK" if not malos else f"{malos} caminos con problema")
    return malos

if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
