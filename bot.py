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

GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent"

PROMPT_SISTEMA_RETIE = """
Eres un Ingeniero Electricista Colombiano experto en normatividad y diseño de sistemas de medida, especializado estrictamente en el RETIE (Reglamento Técnico de Instalaciones Eléctricas de Colombia).
1. Toda respuesta debe alinearse con el RETIE vigente (Resolución 40117 de 2024).
2. Siempre cita el artículo, sección o tabla del RETIE que respalda tu respuesta.
3. Utiliza viñetas, negritas y lenguaje formal de ingeniería en Markdown.
4. Si algo viola las distancias de seguridad, adviértelo con advertencias visibles con el emoji de advertencia.
"""

def _resumen(cfg):
    return f"📐 *Especificación de Medida Detectada:*\n• Tipo: {cfg.get('tipo')}\n• TC: {cfg.get('rel_tc', 'Directo')}\n• TP: {cfg.get('rel_tp', 'Directo')}"

def _menu_kbd(cfg):
    botones = [
        [InlineKeyboardButton(f"Tipo: {cfg.get('tipo', 'directa')}", callback_data="toggle_tipo")],
        [InlineKeyboardButton("Modificar Relaciones (TC/TP)", callback_data="m_rel")],
        [InlineKeyboardButton("Generar Plano", callback_data="m_listo"),
         InlineKeyboardButton("Cancelar", callback_data="m_cancelar")],
    ]
    return InlineKeyboardMarkup(botones)

async def _enviar(update_or_query, cfg):
    msg = update_or_query.message if isinstance(update_or_query, Update) else update_or_query.message
    await msg.reply_chat_action("upload_photo")
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_name = tmp.name
        diagram_engine.generar_diagrama(cfg, tmp_name)
        with open(tmp_name, "rb") as foto:
            await msg.reply_photo(photo=foto, caption="Aqui tienes tu diagrama de conexiones. Exito!")
        os.remove(tmp_name)
    except Exception as e:
        log.error(f"Error generando imagen: {e}")
        await msg.reply_text(f"Error al renderizar el grafico: {str(e)}")

async def _procesar_texto(update: Update, texto_usuario: str):
    texto_limpio = texto_usuario.strip()
    texto_lower = texto_limpio.lower()
    palabras_diagrama = ["unifilar", "conexiones", "esquema", "plano", "dibuja", "grafica", "diagrama"]
    cfg, entendido, _ = parse_spec(texto_limpio)
    pide_diagrama = any(p in texto_lower for p in palabras_diagrama) or (entendido and "retie" not in texto_lower)

    if pide_diagrama:
        log.info(f"Solicitud de diagrama: {texto_limpio}")
        await update.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(update, cfg)
        return

    if not GEMINI_KEY:
        await update.message.reply_text("Error de configuracion: GEMINI_API_KEY no definida.")
        return

    await update.message.reply_chat_action("typing")

    try:
        log.info(f"Enviando consulta a Gemini: '{texto_limpio}'")
        prompt_final = f"{PROMPT_SISTEMA_RETIE}\n\nCONSULTA DEL USUARIO:\n{texto_limpio}"
        payload = {"contents": [{"parts": [{"text": prompt_final}]}]}

        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                GEMINI_URL,
                json=payload,
                params={"key": GEMINI_KEY},
                headers={"Content-Type": "application/json"},
            )

        res_json = response.json()

        if response.status_code == 200:
            texto_respuesta = res_json["candidates"][0]["content"]["parts"][0]["text"]
            await update.message.reply_text(texto_respuesta, parse_mode="Markdown")
            log.info("Respuesta RETIE enviada correctamente.")
        else:
            error_msg = res_json.get("error", {}).get("message", "Error desconocido.")
            await update.message.reply_text(f"Error API Google ({response.status_code}): {error_msg}")

    except httpx.TimeoutException:
        await update.message.reply_text("La consulta tardo demasiado. Intenta de nuevo.")
    except Exception as e:
        log.error(f"Fallo critico Gemini: {e}")
        await update.message.reply_text(f"Error en modulo RETIE: {str(e)}")

async def _procesar_texto_libre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get("esperando_rel"):
        ctx.user_data["esperando_rel"] = False
        cfg = ctx.user_data.get("cfg", dict(DEFAULT))
        txt = update.message.text.strip().lower()
        if txt != "listo":
            for a, b in re.findall(r"\b(\d{2,6})\s*/\s*(\d{1,4})\b", txt):
                if int(b) in (1, 5): cfg["rel_tc"] = f"{a}/{b}"
                else: cfg["rel_tp"] = f"{a}/{b}"
        await update.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(update, cfg)
        return
    await _procesar_texto(update, update.message.text)

async def _boton(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    cfg = ctx.user_data.get("cfg", dict(DEFAULT))

    if data == "m_listo":
        await query.message.delete()
        await query.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(query, cfg)
        return
    if data == "m_cancelar":
        await query.edit_message_text("Configuracion cancelada.")
        return
    if data.startswith("set_"):
        partes = data.split("_")
        k, v = partes[1], partes[2]
        if v == "true": v = True
        elif v == "false": v = False
        cfg[k] = v
        ctx.user_data["cfg"] = cfg
    if data == "m_rel":
        ctx.user_data["esperando_rel"] = True
        await query.edit_message_text("Escribe las relaciones en formato IP/IS.\nEjemplo: 200/5 13200/120 o escribe listo.")
        return
    await query.edit_message_text(
        "Configurador de Medida\nSelecciona las opciones:",
        reply_markup=_menu_kbd(cfg),
    )

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola! Soy tu asistente de Ingenieria Electrica.\n\n- Para planos escribe: unifilar, conexiones, diagrama\n- Para normativa preguntame sobre el RETIE")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Escribe tu pregunta tecnica sobre el RETIE o solicita un diagrama indicando el tipo de medida.")

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cfg"] = dict(DEFAULT)
    await update.message.reply_text("Configurador de Medida:", reply_markup=_menu_kbd(dict(DEFAULT)))

async def cmd_diagrama(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Envia los parametros, ejemplo: indirecta trifasica CENS 200/5")

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Error Fatal: define BOT_TOKEN antes de iniciar.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ayuda", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("diagrama", cmd_diagrama))
    app.add_handler(CallbackQueryHandler(_boton))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _procesar_texto_libre))
    print("Bot encendido. Presiona Ctrl+C para salir.")
    app.run_polling()

if __name__ == "__main__":
    main()
