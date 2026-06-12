# -*- coding: utf-8 -*-
import os, tempfile, logging, re
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)
import diagram_engine
from parser import parse_spec, DEFAULT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("medidor-bot")

GEMINI_KEY   = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent"

PROMPT_SISTEMA_RETIE = (
    "Eres un experto en electricidad colombiano que explica las normas del RETIE de forma clara.\n"
    "Responde SIEMPRE en dos partes:\n"
    "1. RESUMEN SIMPLE: lenguaje cotidiano, max 3 oraciones, usa emojis\n"
    "2. DETALLE TECNICO: cita articulo exacto del RETIE (Resolucion 40117 de 2024), valores exactos\n"
    "Si algo es peligroso adviertelo con advertencia visible en ambas secciones.\n"
    "IMPORTANTE: no uses asteriscos dobles (**) ni caracteres especiales de Markdown en tu respuesta."
)

AYUDA = (
    "Ingeniero de diseno electrico\n\n"
    "Diagramas: usa /menu o escribeme:\n"
    "indirecta trifasica CENS 200/5 13200/120\n\n"
    "Consultas RETIE: preguntame cualquier duda normativa.\n\n"
    "Usa /menu para el configurador guiado."
)

# ── Generacion de diagramas ────────────────────────────────────────────────────
def _generar(cfg):
    salida = cfg.get("salida", "conexiones")
    out = []
    if salida in ("conexiones", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        diagram_engine.draw(cfg, t.name)
        out.append(("Diagrama de conexiones", t.name))
    if salida in ("unifilar", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        if cfg.get("unifilar_trafo"):
            diagram_engine.draw_unifilar_trafo(cfg, t.name)
        else:
            diagram_engine.draw_unifilar(cfg, t.name)
        out.append(("Diagrama unifilar", t.name))
    return out

def _resumen(cfg):
    sis = {
        "mono":    "Monofasica",
        "bifasico":"Bifasica",
        "tri3h":   "Trifasica 3 hilos (2 elem.)",
        "tri4h":   "Trifasica 4 hilos (3 elem.)"
    }.get(cfg.get("sistema","tri4h"), "Trifasica")
    txt = f"Medida {cfg.get('tipo','indirecta')} | {sis} | Norma {cfg.get('norma','RA8')}"
    if cfg.get("respaldo"):          txt += " | Principal+Chequeo"
    if cfg.get("rel_tc"):            txt += f" | RTC {cfg['rel_tc']}"
    if cfg.get("rel_tp"):            txt += f" | RTP {cfg['rel_tp']}"
    if cfg.get("conexion"):          txt += f" | Conexion {cfg['conexion']}"
    if cfg.get("instalacion"):       txt += f" | {cfg['instalacion'].capitalize()}"
    if cfg.get("trafo_uso"):         txt += f" ({cfg['trafo_uso']})"
    if cfg.get("trafo_kva"):         txt += f" | Trafo {cfg['trafo_kva']} kVA"
    if cfg.get("n_trafos"):          txt += f" x{cfg['n_trafos']}"
    if cfg.get("trafo_tipo"):        txt += f" {cfg['trafo_tipo']}"
    if cfg.get("tc_pos"):            txt += f" | TC {cfg['tc_pos']} totalizador"
    if cfg.get("tc_amp"):            txt += f" {cfg['tc_amp']} A"
    if cfg.get("proteccion_amp"):    txt += f" | Proteccion {cfg['proteccion_amp']} A"
    if cfg.get("interruptor"):       txt += f" | Interruptor {cfg['interruptor']}"
    if cfg.get("interruptor_pos"):   txt += f" ({cfg['interruptor_pos']} medidor)"
    if cfg.get("seccionamiento"):    txt += f" | Con seccionamiento"
    return txt

async def _enviar_foto(mensaje, cfg):
    imgs = _generar(cfg)
    for titulo, path in imgs:
        with open(path, "rb") as f:
            await mensaje.reply_photo(
                photo=f,
                caption=f"{titulo}\n{_resumen(cfg)}"
            )
        try: os.remove(path)
        except OSError: pass

# ── Modulo experto RETIE ─────────────────────────────────────────────────────
async def _consulta_retie(update: Update, texto: str):
    if not GEMINI_KEY:
        await update.message.reply_text("Error: GEMINI_API_KEY no definida.")
        return
    await update.message.reply_chat_action("typing")
    try:
        payload = {"contents": [{"parts": [{"text": f"{PROMPT_SISTEMA_RETIE}\n\nCONSULTA:\n{texto}"}]}]}
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                GEMINI_URL, json=payload,
                params={"key": GEMINI_KEY},
                headers={"Content-Type": "application/json"}
            )
        res_json = response.json()
        if response.status_code == 200:
            respuesta = res_json["candidates"][0]["content"]["parts"][0]["text"]
            respuesta = respuesta.replace("**", "").replace("__", "")
            await update.message.reply_text(respuesta)
        else:
            msg = res_json.get("error", {}).get("message", "Error desconocido.")
            await update.message.reply_text(f"Error API ({response.status_code}): {msg}")
    except httpx.TimeoutException:
        await update.message.reply_text("Timeout. Intenta de nuevo.")
    except Exception as e:
        log.error(f"Error Gemini: {e}")
        await update.message.reply_text(f"Error: {str(e)}")

async def _procesar_texto(update, texto):
    cfg, entendido, faltante = parse_spec(texto)
    palabras_diagrama = [
        "unifilar","conexiones","esquema","plano","dibuja",
        "grafica","diagrama","directa","semidirecta","indirecta",
        "monofasica","trifasica"
    ]
    if any(p in texto.lower() for p in palabras_diagrama):
        if faltante:
            await update.effective_message.reply_text(
                "Lo genero con lo que entendi. Te recomiendo agregar: " + ", ".join(faltante)
            )
        try:
            await _enviar_foto(update.effective_message, cfg)
        except Exception as e:
            log.error(f"Error diagrama: {e}")
            await update.effective_message.reply_text(f"Error generando diagrama: {e}")
    else:
        await _consulta_retie(update, texto)

# ── Comandos ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA)

async def cmd_diagrama(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = " ".join(ctx.args) if ctx.args else ""
    if not texto:
        await update.message.reply_text("Ejemplo: /diagrama indirecta tri4h CENS 200/5 13200/120")
        return
    await _procesar_texto(update, texto)

# ── Menu guiado ───────────────────────────────────────────────────────────────
def _kb(opciones, prefijo):
    btns = [InlineKeyboardButton(txt, callback_data=f"{prefijo}:{val}") for txt, val in opciones]
    return [btns[i:i+2] for i in range(0, len(btns), 2)]

def _reset_flags(ctx):
    for k in ["esperando_kva","esperando_interruptor","esperando_rel",
              "esperando_tc_amp","esperando_proteccion","esperando_n_trafos",
              "esperando_kva_lista","trafos_kva_lista","trafos_idx","trafos_total"]:
        ctx.user_data.pop(k, None)

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cfg"] = dict(DEFAULT)
    _reset_flags(ctx)
    kb = _kb([("Directa","directa"),("Semidirecta","semidirecta"),("Indirecta","indirecta")], "tipo")
    await update.message.reply_text("1 - Tipo de medida:", reply_markup=InlineKeyboardMarkup(kb))

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cfg = ctx.user_data.setdefault("cfg", dict(DEFAULT))
    campo, val = q.data.split(":", 1)

    # ── Pasos base (sin cambios respecto al flujo original) ─────────────────
    if campo == "tipo":
        cfg["tipo"] = val
        kb = _kb([("Monofasica","mono"),("Bifasica","bifasico"),("Trif. 2 elem","tri3h"),("Trif. 3 elem","tri4h")], "sistema")
        await q.edit_message_text("2 - Sistema:", reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "sistema":
        cfg["sistema"] = val
        kb = _kb([("CENS","CENS"),("RA8 (nacional)","RA8")], "norma")
        await q.edit_message_text("3 - Norma:", reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "norma":
        cfg["norma"] = val
        kb = _kb([("Sin respaldo","no"),("Principal + Chequeo","si")], "respaldo")
        await q.edit_message_text("4 - Medidor de respaldo?", reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "respaldo":
        cfg["respaldo"] = (val == "si")
        kb = _kb([("Conexiones","conexiones"),("Unifilar","unifilar"),("Ambos","ambos")], "salida")
        await q.edit_message_text("5 - Que diagrama?", reply_markup=InlineKeyboardMarkup(kb))

    # ── "salida" reparte segun tipo de medida ────────────────────────────────
    elif campo == "salida":
        cfg["salida"] = val
        if val in ("conexiones", "ambos") and cfg["tipo"] == "directa":
            kb = _kb([("Simetrica (Americana)","simetrica"),("Asimetrica (Europea)","asimetrica")], "conexion")
            await q.edit_message_text("6 - Tipo de conexion del medidor:", reply_markup=InlineKeyboardMarkup(kb))
        elif val in ("unifilar", "ambos"):
            await _ir_a_pregunta_instalacion(q, cfg)
        else:
            await _finalizar_o_rel(q, ctx, cfg)

    # ── DIRECTA: simetrica/asimetrica -> instalacion ─────────────────────────
    elif campo == "conexion":
        cfg["conexion"] = val
        if cfg["salida"] in ("unifilar","ambos"):
            await _ir_a_pregunta_instalacion(q, cfg)
        else:
            await _finalizar_o_rel(q, ctx, cfg)

    # ── Pregunta comun: Barraje o Transformador ──────────────────────────────
    elif campo == "tipo_instalacion":
        cfg["instalacion"] = val  # "barraje" | "trafo"
        tipo = cfg["tipo"]

        if val == "barraje":
            if tipo == "indirecta":
                # Indirecta conectada a barraje (raro, pero seguir flujo de seccionamiento)
                kb = _kb([("Directo a la red","red"),("Con seccionamiento","seccion")], "conexion_red")
                await q.edit_message_text("7 - La medida esta conectada directo a la red o tiene seccionamiento?", reply_markup=InlineKeyboardMarkup(kb))
            elif tipo == "semidirecta":
                kb = _kb([("Antes del totalizador","antes"),("Despues del totalizador","despues")], "tc_pos")
                await q.edit_message_text("7 - El TC (transformador de corriente) esta antes o despues del totalizador principal?", reply_markup=InlineKeyboardMarkup(kb))
            else:  # directa
                kb = _kb([("Si","breaker_si"),("No","breaker_no")], "tiene_breaker")
                await q.edit_message_text("7 - Tiene interruptor/breaker de proteccion?", reply_markup=InlineKeyboardMarkup(kb))

        else:  # trafo
            if tipo == "indirecta":
                ctx.user_data["esperando_n_trafos"] = True
                await q.edit_message_text("7 - Cuantos transformadores hay? (despues de la medida)\nEscribe solo el numero, ej: 1, 2, 3")
            else:
                kb = _kb([("Exclusivo","exclusivo"),("Compartido","compartido")], "trafo_uso")
                await q.edit_message_text("7 - El transformador es exclusivo o compartido?", reply_markup=InlineKeyboardMarkup(kb))

    # ── INDIRECTA: conectada a red o seccionamiento (cuando instalacion=barraje) ─
    elif campo == "conexion_red":
        cfg["seccionamiento"] = (val == "seccion")
        ctx.user_data["esperando_n_trafos"] = True
        await q.edit_message_text("8 - Cuantos transformadores hay despues de la medida?\nEscribe solo el numero, ej: 1, 2, 3")

    # ── SEMIDIRECTA + barraje: posicion del TC ───────────────────────────────
    elif campo == "tc_pos":
        cfg["tc_pos"] = val  # "antes" | "despues"
        ctx.user_data["esperando_tc_amp"] = True
        await q.edit_message_text("8 - De cuantos amperios es el TC?\nEscribe solo el numero, ej: 200")

    # ── DIRECTA + barraje: tiene breaker? ────────────────────────────────────
    elif campo == "tiene_breaker":
        if val == "breaker_si":
            kb = _kb([("Antes del medidor","antes"),("Despues del medidor","despues")], "breaker_pos")
            await q.edit_message_text("8 - El breaker esta antes o despues del medidor?", reply_markup=InlineKeyboardMarkup(kb))
        else:
            cfg["interruptor_pos"] = None
            if cfg["tipo"] == "indirecta":
                ctx.user_data["esperando_rel"] = True
                await q.edit_message_text("Envia las relaciones TC y TP (ej. 200/5 13200/120) o escribe listo.")
            else:
                await q.edit_message_text(_resumen(cfg))
                await _enviar_foto(q.message, cfg)

    elif campo == "breaker_pos":
        cfg["interruptor_pos"] = val  # "antes" | "despues"
        ctx.user_data["esperando_interruptor"] = True
        await q.edit_message_text("9 - De cuantos amperios es el breaker?\nEscribe solo el numero, ej: 100")

    # ── SEMIDIRECTA + trafo: exclusivo/compartido -> kVA ─────────────────────
    elif campo == "trafo_uso":
        cfg["trafo_uso"] = val  # "exclusivo" | "compartido"
        ctx.user_data["esperando_kva"] = True
        await q.edit_message_text("8 - Cuantos kVA tiene el transformador?\nEscribe solo el numero, ej: 15 o 37.5")

    elif campo == "tipo_trafo":
        cfg["trafo_tipo"] = val  # "monofasico"|"bifasico"|"trifasico"
        if cfg["tipo"] == "semidirecta":
            ctx.user_data["esperando_tc_amp"] = True
            await q.edit_message_text("10 - De cuantos amperios son los TC?\nEscribe solo el numero, ej: 200")
        else:
            # directa con transformador
            kb = _kb([("Si","breaker_si"),("No","breaker_no")], "tiene_breaker")
            await q.edit_message_text("9 - Tiene interruptor/breaker de proteccion?", reply_markup=InlineKeyboardMarkup(kb))


async def _ir_a_pregunta_instalacion(q, cfg):
    kb = _kb([("Barraje","barraje"),("Transformador","trafo")], "tipo_instalacion")
    await q.edit_message_text("6 - La instalacion esta conectada a un barraje o a un transformador?", reply_markup=InlineKeyboardMarkup(kb))

async def _finalizar_o_rel(q, ctx, cfg):
    if cfg["tipo"] == "indirecta":
        ctx.user_data["esperando_rel"] = True
        await q.edit_message_text("Envia las relaciones TC y TP (ej. 200/5 13200/120) o escribe listo.")
    else:
        await q.edit_message_text(_resumen(cfg))
        await _enviar_foto(q.message, cfg)


# ── Manejador de texto (respuestas numericas y flujo final) ─────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg = ctx.user_data.get("cfg", dict(DEFAULT))
    txt = update.message.text.strip()

    # --- Numero de transformadores (INDIRECTA) ---
    if ctx.user_data.get("esperando_n_trafos"):
        ctx.user_data["esperando_n_trafos"] = False
        try:
            n = max(1, int(txt))
        except ValueError:
            n = 1
        cfg["n_trafos"] = n
        ctx.user_data["cfg"] = cfg
        ctx.user_data["trafos_kva_lista"] = []
        ctx.user_data["trafos_idx"] = 1
        ctx.user_data["trafos_total"] = n
        ctx.user_data["esperando_kva_lista"] = True
        await update.message.reply_text(f"kVA del transformador 1 de {n}?\nEscribe solo el numero, ej: 15")
        return

    # --- kVA de cada transformador (lista, INDIRECTA) ---
    if ctx.user_data.get("esperando_kva_lista"):
        lista = ctx.user_data.get("trafos_kva_lista", [])
        lista.append(txt)
        ctx.user_data["trafos_kva_lista"] = lista
        idx = ctx.user_data.get("trafos_idx", 1)
        total = ctx.user_data.get("trafos_total", 1)
        if idx < total:
            ctx.user_data["trafos_idx"] = idx + 1
            await update.message.reply_text(f"kVA del transformador {idx+1} de {total}?\nEscribe solo el numero, ej: 15")
            return
        else:
            ctx.user_data["esperando_kva_lista"] = False
            cfg["trafo_kva"] = " + ".join(lista)
            cfg["trafo_kva_lista"] = lista
            ctx.user_data["cfg"] = cfg
            # Indirecta: ahora pedir relaciones TC/TP (medida)
            ctx.user_data["esperando_rel"] = True
            await update.message.reply_text("Ahora, envia las relaciones TC y TP de la medida (ej. 200/5 13200/120) o escribe listo.")
            return

    # --- kVA transformador unico (SEMIDIRECTA / DIRECTA) ---
    if ctx.user_data.get("esperando_kva"):
        ctx.user_data["esperando_kva"] = False
        cfg["trafo_kva"] = txt
        ctx.user_data["cfg"] = cfg
        kb = _kb([("Monofasico","monofasico"),("Bifasico","bifasico"),("Trifasico","trifasico")], "tipo_trafo")
        await update.message.reply_text("9 - El transformador es monofasico, bifasico o trifasico?", reply_markup=InlineKeyboardMarkup(kb))
        return

    # --- Amperios del TC (SEMIDIRECTA) ---
    if ctx.user_data.get("esperando_tc_amp"):
        ctx.user_data["esperando_tc_amp"] = False
        cfg["tc_amp"] = txt
        ctx.user_data["cfg"] = cfg
        if cfg.get("instalacion") == "trafo":
            ctx.user_data["esperando_proteccion"] = True
            await update.message.reply_text("11 - De cuantos amperios es la proteccion (totalizador)?\nEscribe solo el numero, ej: 200")
        else:
            # barraje: ya tenemos todo, generar
            await update.message.reply_text(_resumen(cfg))
            await _enviar_foto(update.message, cfg)
        return

    # --- Amperios de la proteccion (SEMIDIRECTA + trafo) ---
    if ctx.user_data.get("esperando_proteccion"):
        ctx.user_data["esperando_proteccion"] = False
        cfg["proteccion_amp"] = txt
        cfg["interruptor"] = f"{txt} A"
        ctx.user_data["cfg"] = cfg
        await update.message.reply_text(_resumen(cfg))
        await _enviar_foto(update.message, cfg)
        return

    # --- Amperios del breaker/interruptor (DIRECTA) ---
    if ctx.user_data.get("esperando_interruptor"):
        ctx.user_data["esperando_interruptor"] = False
        cfg["interruptor"] = f"{txt} A"
        ctx.user_data["cfg"] = cfg
        if cfg["tipo"] == "indirecta":
            ctx.user_data["esperando_rel"] = True
            await update.message.reply_text("Envia las relaciones TC y TP (ej. 200/5 13200/120) o escribe listo.")
        else:
            await update.message.reply_text(_resumen(cfg))
            await _enviar_foto(update.message, cfg)
        return

    # --- Relaciones TC/TP (medida indirecta/semidirecta) ---
    if ctx.user_data.get("esperando_rel"):
        ctx.user_data["esperando_rel"] = False
        t = txt.lower()
        if t != "listo":
            for a, b in re.findall(r"\b(\d{2,6})\s*/\s*(\d{1,4})\b", t):
                if int(b) in (1, 5): cfg["rel_tc"] = f"{a}/{b}"
                else:                cfg["rel_tp"] = f"{a}/{b}"
        await update.message.reply_text(_resumen(cfg))
        await _enviar_foto(update.message, cfg)
        return

    # --- Texto libre ---
    await _procesar_texto(update, update.message.text)

# ── Arranque ──────────────────────────────────────────────────────────────────
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Define BOT_TOKEN antes de iniciar.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("ayuda",    cmd_help))
    app.add_handler(CommandHandler("menu",     cmd_menu))
    app.add_handler(CommandHandler("diagrama", cmd_diagrama))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot iniciado.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
