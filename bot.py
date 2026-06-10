# -*- coding: utf-8 -*-
"""
Bot de Telegram - Ingeniero de diseno electrico.
Genera diagramas de CONEXIONES y/o UNIFILAR de sistemas de medida.

Entrada:
  - Texto libre:  "indirecta trifasica 3 elementos norma CENS 200/5 13200/120"
                  "unifilar semidirecta 300/5 13.2 kv"
  - Comando:      /diagrama tipo=indirecta sistema=tri4h norma=RA8 rtc=200/5 rtp=13200/120
  - Menu guiado:  /menu

Requisitos: python-telegram-bot>=21, matplotlib
Variable de entorno:  BOT_TOKEN
"""
import os, tempfile, logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

import diagram_engine
from parser import parse_spec, DEFAULT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("medidor-bot")

AYUDA = (
    "*Ingeniero de diseno electrico* \U0001F50C\n\n"
    "Indicame las especificaciones de la medida y te genero el *diagrama de conexiones* "
    "y/o el *diagrama unifilar*.\n\n"
    "*Lenguaje natural:*\n"
    "`indirecta trifasica 3 elementos norma CENS 200/5 13200/120`\n"
    "`unifilar semidirecta 300/5 13.2 kv`\n"
    "`indirecta 3 elementos con respaldo 200/5 13200/120`\n\n"
    "*Comando con parametros:*\n"
    "`/diagrama tipo=indirecta sistema=tri4h norma=CENS rtc=200/5 rtp=13200/120 respaldo=si`\n\n"
    "*Campos:*\n"
    "• tipo: directa | semidirecta | indirecta\n"
    "• sistema: mono | bifasico | tri3h (2 elem) | tri4h (3 elem)\n"
    "• norma: CENS | RA8\n"
    "• rtc / rtp: relaciones (ej. 200/5, 13200/120)\n"
    "• respaldo: si  (medidor principal + chequeo)\n"
    "• agrega *unifilar* para el diagrama unifilar (o *unifilar y conexiones* para ambos)\n\n"
    "Tambien: /menu para elegir con botones."
)

# ----------------------------- generacion -----------------------------
def _generar(cfg):
    """Devuelve lista de (titulo, ruta_png) segun cfg['salida']."""
    salida = cfg.get("salida", "conexiones")
    out = []
    if salida in ("conexiones", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        diagram_engine.draw(cfg, t.name); out.append(("Diagrama de conexiones", t.name))
    if salida in ("unifilar", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        if cfg.get("unifilar_trafo"):
            diagram_engine.draw_unifilar_trafo(cfg, t.name)
        else:
            diagram_engine.draw_unifilar(cfg, t.name)
        out.append(("Diagrama unifilar", t.name))
    return out

def _resumen(cfg):
    sis = {"mono":"Monofasica","bifasico":"Bifasica",
           "tri3h":"Trifasica 3 hilos (2 elem.)","tri4h":"Trifasica 4 hilos (3 elem.)"}[cfg["sistema"]]
    txt = f"\U0001F4D0 Medida *{cfg['tipo']}* | {sis} | Norma *{cfg['norma']}*"
    if cfg.get("respaldo"): txt += " | Principal+Chequeo"
    if cfg.get("rel_tc"): txt += f" | RTC {cfg['rel_tc']}"
    if cfg.get("rel_tp"): txt += f" | RTP {cfg['rel_tp']}"
    return txt

async def _enviar(update, cfg):
    imgs = _generar(cfg)
    for titulo, path in imgs:
        with open(path, "rb") as f:
            await update.effective_message.reply_photo(
                photo=f, caption=f"*{titulo}*\n{_resumen(cfg)}", parse_mode="Markdown")
        try: os.remove(path)
        except OSError: pass

# ----------------------------- handlers -----------------------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, parse_mode="Markdown")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, parse_mode="Markdown")

async def cmd_diagrama(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = " ".join(ctx.args) if ctx.args else ""
    if not texto:
        await update.message.reply_text("Dame las especificaciones. Ej:\n"
            "`/diagrama indirecta tri4h CENS 200/5 13200/120`", parse_mode="Markdown")
        return
    await _procesar_texto(update, texto)

async def _procesar_texto(update, texto):
    cfg, entendido, faltante = parse_spec(texto)
    if faltante:
        await update.effective_message.reply_text(
            "Lo genero con lo que entendi; te recomiendo agregar: " + ", ".join(faltante) + ".")
    try:
        await _enviar(update, cfg)
    except Exception as e:
        log.exception("error generando diagrama")
        await update.effective_message.reply_text(f"⚠ No pude generar el diagrama: {e}")

# ----------------------------- menu con botones -----------------------------
def _kb(opciones, prefijo):
    btns = [InlineKeyboardButton(txt, callback_data=f"{prefijo}:{val}") for txt, val in opciones]
    return [btns[i:i+2] for i in range(0, len(btns), 2)]

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cfg"] = dict(DEFAULT)
    kb = _kb([("Directa","directa"),("Semidirecta","semidirecta"),("Indirecta","indirecta")], "tipo")
    await update.message.reply_text("1️⃣ Tipo de medida:", reply_markup=InlineKeyboardMarkup(kb))

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cfg = ctx.user_data.setdefault("cfg", dict(DEFAULT))
    campo, val = q.data.split(":", 1)

    if campo == "tipo":
        cfg["tipo"] = val
        kb = _kb([("Monofasica","mono"),("Bifasica","bifasico"),
                  ("Trif. 2 elem","tri3h"),("Trif. 3 elem","tri4h")], "sistema")
        await q.edit_message_text("2️⃣ Sistema:", reply_markup=InlineKeyboardMarkup(kb))
    elif campo == "sistema":
        cfg["sistema"] = val
        kb = _kb([("CENS","CENS"),("RA8 (nacional)","RA8")], "norma")
        await q.edit_message_text("3️⃣ Norma:", reply_markup=InlineKeyboardMarkup(kb))
    elif campo == "norma":
        cfg["norma"] = val
        kb = _kb([("Sin respaldo","no"),("Principal + Chequeo","si")], "respaldo")
        await q.edit_message_text("4️⃣ ¿Medidor de respaldo?", reply_markup=InlineKeyboardMarkup(kb))
    elif campo == "respaldo":
        cfg["respaldo"] = (val == "si")
        kb = _kb([("Conexiones","conexiones"),("Unifilar","unifilar"),("Ambos","ambos")], "salida")
        await q.edit_message_text("5️⃣ ¿Que diagrama?", reply_markup=InlineKeyboardMarkup(kb))
    elif campo == "salida":
        cfg["salida"] = val
        if cfg["tipo"] == "indirecta":
            ctx.user_data["esperando_rel"] = True
            await q.edit_message_text(
                "6️⃣ Envia las relaciones TC y TP (ej. `200/5 13200/120`) "
                "en un mensaje, o escribe `listo` para generar sin ellas.", parse_mode="Markdown")
        else:
            await q.edit_message_text(_resumen(cfg), parse_mode="Markdown")
            await _enviar(q, cfg)

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Captura relaciones si el menu las espera; si no, procesa como texto libre."""
    if ctx.user_data.get("esperando_rel"):
        ctx.user_data["esperando_rel"] = False
        cfg = ctx.user_data.get("cfg", dict(DEFAULT))
        txt = update.message.text.strip().lower()
        if txt != "listo":
            import re
            for a, b in re.findall(r"\b(\d{2,6})\s*/\s*(\d{1,4})\b", txt):
                if int(b) in (1, 5): cfg["rel_tc"] = f"{a}/{b}"
                else: cfg["rel_tp"] = f"{a}/{b}"
        await update.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(update, cfg)
        return
    await _procesar_texto(update, update.message.text)

# ----------------------------- main -----------------------------
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Define la variable de entorno BOT_TOKEN (token de @BotFather).")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ayuda", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("diagrama", cmd_diagrama))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
