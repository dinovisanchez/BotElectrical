#!/usr/bin/env python3
"""Opciones nuevas del menu: Estilo del unifilar (limpio/detallado) y Estado del
seccionador (cerrado/abierto). Pulsa los botones REALES de la pantalla de
confirmacion (on_button) y verifica texto, botones, cfg y el renderer usado."""
import sys, os, asyncio, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
logging.disable(logging.CRITICAL)
import bot, diagram_engine
from parser import DEFAULT

bot._genai_client = None

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
    def __init__(self, ev, data):
        self.effective_user = None; self.callback_query = Query(data, ev); self.message = None
        self.effective_message = self.callback_query.message
class Ctx:
    def __init__(self, cfg): self.user_data = {"cfg": cfg, "paso_n": 8}; self.bot = None

def cfg_ind(**kw):
    c = dict(DEFAULT, tipo="indirecta", sistema="tri4h", salida="unifilar", norma="CENS", instalacion="trafo",
             n_trafos=1, trafo_kva="700", trafo_uso="exclusivo", rel_tc="50/5", rel_tp="13200/120",
             seccionador="antes", respaldo=False)
    c.update(kw); return c

def botones(ev):
    mk = next((e[2] for e in reversed(ev) if e[2]), None)
    return [b.callback_data for row in mk.inline_keyboard for b in row] if mk else []

def texto(ev):
    return [e[1] for e in ev if e[0] == "text"][-1]

async def pulsar(ctx, ev, data):
    n0 = len(ev); await bot.on_button(Upd(ev, data), ctx); return ev[n0:]

async def main():
    malos = 0
    def chk(ok, msg):
        nonlocal malos; malos += not ok; print("OK  " if ok else "MAL ", msg)

    # --- Pantalla de confirmacion: indirecta + unifilar ---
    ctx, ev = Ctx(cfg_ind()), []
    await bot._paso_confirmar(Msg(ev), ctx.user_data["cfg"], edit=False)
    t, bs = texto(ev), botones(ev)
    chk("Estilo        Limpio (vertical)" in t, "resumen muestra 'Estilo  Limpio (vertical)'")
    chk("cerrado" in t and "Seccionador" in t, "resumen muestra el seccionador 'cerrado'")
    chk("editval:estilo:detallado" in bs and "editval:seccionador_estado:abierto" in bs,
        "botones de un toque: estilo->detallado y seccionador->abierto")

    # --- Toggle de estilo y de estado con los botones reales ---
    ev = await pulsar(ctx, [], "editval:estilo:detallado")
    chk(ctx.user_data["cfg"]["estilo"] == "detallado" and "Detallado" in texto(ev), "toque 'Estilo' -> detallado y el resumen lo refleja")
    chk("editval:estilo:limpio" in botones(ev), "el boton ahora ofrece volver a 'limpio'")
    ev = await pulsar(ctx, [], "editval:seccionador_estado:abierto")
    chk(ctx.user_data["cfg"]["seccionador_estado"] == "abierto" and "abierto" in texto(ev), "toque 'Seccionador' -> abierto")
    chk(ctx.user_data["paso_n"] == 8, "el flujo lineal (paso_n) queda intacto")

    # --- Submenu Editar: ambos campos, y se pueden elegir ---
    ev = await pulsar(ctx, [], "generar:editar")
    chk("editcampo:estilo" in botones(ev) and "editcampo:seccionador_estado" in botones(ev), "submenu Editar lista 'estilo' y 'seccionador_estado'")
    ev = await pulsar(ctx, [], "editcampo:seccionador_estado")
    chk("editval:seccionador_estado:cerrado" in botones(ev), "Editar -> Estado del seccionador ofrece 'cerrado'")
    ev = await pulsar(ctx, [], "editval:seccionador_estado:cerrado")
    chk(ctx.user_data["cfg"]["seccionador_estado"] == "cerrado", "se vuelve a 'cerrado'")

    # --- No aplica: semidirecta, multi-celda, solo conexiones, sin seccionador ---
    for nombre, c in [("semidirecta", cfg_ind(tipo="semidirecta")),
                      ("multi-celda", cfg_ind(n_trafos=3, trafo_kva_list=["500", "300", "300"])),
                      ("solo conexiones", cfg_ind(salida="conexiones"))]:
        cx, e = Ctx(c), []
        await bot._paso_confirmar(Msg(e), c, edit=False)
        chk("editval:estilo:" not in " ".join(botones(e)) and "Estilo" not in texto(e), f"{nombre}: NO ofrece estilo")
    cx, e = Ctx(cfg_ind(seccionador="")), []
    await bot._paso_confirmar(Msg(e), cx.user_data["cfg"], edit=False)
    chk("seccionador_estado" not in " ".join(botones(e)), "sin seccionador: NO ofrece estado")

    # --- Renderer usado + aviso de seccionador abierto ---
    usados = []
    orig = diagram_engine.draw_unifilar_indirecta_pro
    def espia(cfg, out): usados.append("limpio"); return orig(cfg, out)
    diagram_engine.draw_unifilar_indirecta_pro = espia
    try:
        for est, esperado in (("limpio", ["limpio"]), ("detallado", [])):
            usados.clear()
            imgs, notas, _ = bot._generar(cfg_ind(estilo=est))
            chk(usados == esperado and os.path.getsize(imgs[0][1]) > 3000, f"estilo={est}: renderer {'limpio' if esperado else 'detallado'} usado")
        _, notas, _ = bot._generar(cfg_ind(seccionador_estado="abierto"))
        chk(any("ABIERTO" in n for n in notas), "seccionador abierto -> aviso de instalacion desenergizada")
        _, notas, _ = bot._generar(cfg_ind())
        chk(not any("ABIERTO" in n for n in notas), "seccionador cerrado -> sin ese aviso")
        # estado tambien en el renderer detallado
        for est in ("cerrado", "abierto"):
            imgs, _, _ = bot._generar(cfg_ind(estilo="detallado", seccionador_estado=est))
            chk(os.path.getsize(imgs[0][1]) > 3000, f"detallado + seccionador {est}")
    finally:
        diagram_engine.draw_unifilar_indirecta_pro = orig

    print("\nRESULTADO:", "TODO OK" if not malos else f"{malos} fallos")
    return malos

if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
