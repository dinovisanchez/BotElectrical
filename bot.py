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
    if cfg.get("respaldo"):       txt += " | Principal+Chequeo"
    if cfg.get("rel_tc"):         txt += f" | RTC {cfg['rel_tc']}"
    if cfg.get("rel_tp"):         txt += f" | RTP {cfg['rel_tp']}"
    if cfg.get("trafo_kva"):      txt += f" | Trafo {cfg['trafo_kva']} kVA"
    if cfg.get("trafo_tipo"):     txt += f" {cfg['trafo_tipo']}"
    if cfg.get("interruptor"):    txt += f" | Interruptor {cfg['interruptor']}"
    if cfg.get("conexion"):       txt += f" | Conexion {cfg['conexion']}"
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

async def _consulta_retie(update, texto):
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
            # Limpiar caracteres que rompen Markdown de Telegram
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

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cfg"] = dict(DEFAULT)
    ctx.user_data["esperando_kva"] = False
    ctx.user_data["esperando_interruptor"] = False
    ctx.user_data["esperando_rel"] = False
    kb = _kb([("Directa","directa"),("Semidirecta","semidirecta"),("Indirecta","indirecta")], "tipo")
    await update.message.reply_text("1 - Tipo de medida:", reply_markup=InlineKeyboardMarkup(kb))

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cfg = ctx.user_data.setdefault("cfg", dict(DEFAULT))
    campo, val = q.data.split(":", 1)

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

    elif campo == "salida":
        cfg["salida"] = val
        # Conexiones directa: preguntar simetrico/asimetrico
        if val in ("conexiones", "ambos") and cfg["tipo"] == "directa":
            kb = _kb([("Simetrica (Americana)","simetrica"),("Asimetrica (Europea)","asimetrica")], "conexion")
            await q.edit_message_text("6 - Tipo de conexion del medidor:", reply_markup=InlineKeyboardMarkup(kb))
        # Unifilar: preguntar transformador o barraje
        elif val in ("unifilar", "ambos"):
            kb = _kb([("Transformador de potencia","trafo"),("Barraje / sin trafo","barraje")], "tipo_instalacion")
            await q.edit_message_text("6 - Tipo de instalacion:", reply_markup=InlineKeyboardMarkup(kb))
        # Conexiones indirecta/semidirecta
        elif cfg["tipo"] == "indirecta":
            ctx.user_data["esperando_rel"] = True
            await q.edit_message_text("6 - Envia las relaciones TC y TP (ej. 200/5 13200/120) o escribe listo.")
        else:
            await q.edit_message_text(_resumen(cfg))
            await _enviar_foto(q.message, cfg)

    elif campo == "conexion":
        cfg["conexion"] = val
        if cfg["tipo"] == "indirecta":
            ctx.user_data["esperando_rel"] = True
            await q.edit_message_text("7 - Envia las relaciones TC y TP (ej. 200/5 13200/120) o escribe listo.")
        else:
            await q.edit_message_text(_resumen(cfg))
            await _enviar_foto(q.message, cfg)

    elif campo == "tipo_instalacion":
        if val == "trafo":
            cfg["unifilar_trafo"] = True
            ctx.user_data["esperando_kva"] = True
            await q.edit_message_text("7 - Cuantos kVA tiene el transformador?\nEscribe solo el numero, ej: 15 o 37.5")
        else:
            cfg["unifilar_trafo"] = False
            if cfg["tipo"] == "indirecta":
                ctx.user_data["esperando_rel"] = True
                await q.edit_message_text("7 - Envia las relaciones TC y TP (ej. 200/5 13200/120) o escribe listo.")
            else:
                await q.edit_message_text(_resumen(cfg))
                await _enviar_foto(q.message, cfg)

    elif campo == "tipo_trafo":
        cfg["trafo_tipo"] = val
        kb = _kb([
            ("Antes de la medida","antes"),
            ("Despues de la medida","despues"),
            ("Antes y despues","ambos_int")
        ], "interruptor_pos")
        await q.edit_message_text("9 - Donde va el interruptor/totalizador?", reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "interruptor_pos":
        cfg["interruptor_pos"] = val
        ctx.user_data["esperando_interruptor"] = True
        await q.edit_message_text("10 - De cuantos amperios es el interruptor?\nEscribe solo el numero, ej: 100")

# ── Manejador de texto ────────────────────────────────────────────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg = ctx.user_data.get("cfg", dict(DEFAULT))

    if ctx.user_data.get("esperando_kva"):
        ctx.user_data["esperando_kva"] = False
        cfg["trafo_kva"] = update.message.text.strip()
        ctx.user_data["cfg"] = cfg
        kb = _kb([("Monofasico","monofasico"),("Bifasico","bifasico"),("Trifasico","trifasico")], "tipo_trafo")
        await update.message.reply_text("8 - El transformador es monofasico, bifasico o trifasico?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if ctx.user_data.get("esperando_interruptor"):
        ctx.user_data["esperando_interruptor"] = False
        cfg["interruptor"] = f"{update.message.text.strip()} A"
        ctx.user_data["cfg"] = cfg
        if cfg["tipo"] == "indirecta":
            ctx.user_data["esperando_rel"] = True
            await update.message.reply_text("11 - Envia las relaciones TC y TP (ej. 200/5 13200/120) o escribe listo.")
        else:
            await update.message.reply_text(_resumen(cfg))
            await _enviar_foto(update.message, cfg)
        return

    if ctx.user_data.get("esperando_rel"):
        ctx.user_data["esperando_rel"] = False
        txt = update.message.text.strip().lower()
        if txt != "listo":
            for a, b in re.findall(r"\b(\d{2,6})\s*/\s*(\d{1,4})\b", txt):
                if int(b) in (1, 5): cfg["rel_tc"] = f"{a}/{b}"
                else:                cfg["rel_tp"] = f"{a}/{b}"
        await update.message.reply_text(_resumen(cfg))
        await _enviar_foto(update.message, cfg)
        return

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
