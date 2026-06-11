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
import os, tempfile, logging, signal
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

import diagram_engine
from parser import parse_spec, DEFAULT

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("medidor-bot")

GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

PROMPT_SISTEMA_RETIE = """
Eres un Ingeniero Electricista Colombiano experto en normatividad y diseño de sistemas de medida, especializado estrictamente en el RETIE (Reglamento Técnico de Instalaciones Eléctricas de Colombia).

Tu objetivo es responder de forma libre, técnica y precisa a las consultas del usuario. Sigue rigurosamente estas reglas:
1. Base Normativa Absoluta: Toda respuesta debe alinearse con las exigencias de seguridad, distancias mínimas, grados de protección (IP/IK) y puesta a tierra del RETIE vigente (Resolución 40117 de 2024).
2. Cita de Artículos: Siempre que dictamines una exigencia técnica (ej. distancias de seguridad, alturas de medidores), DEBES citar el artículo, sección o tabla del RETIE que lo respalda.
3. Formato Profesional: Utiliza viñetas, negritas para conceptos clave y mantén un lenguaje corporativo y formal de ingeniería en Markdown.
4. Advertencia de Seguridad: Si el usuario te pide algo que viole las distancias de seguridad o ponga en riesgo la instalación según el RETIE, adviértelo inmediatamente usando alertas visibles (⚠️).
"""

async def _procesar_texto(update: Update, texto_usuario: str):
    """Analiza si el texto es para un diagrama con Matplotlib o una consulta RETIE."""
    texto_usuario = texto_usuario.strip()
    
    # 1. Verificar si el usuario quiere generar un diagrama eléctrico
    cfg, entendido, faltante = parse_spec(texto_usuario)
    pide_diagrama = "unifilar" in texto_usuario.lower() or "conexiones" in texto_usuario.lower() or entendido
    
    if pide_diagrama:
        log.info(f"Procesando solicitud de diagrama: {texto_usuario}")
        await update.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(update, cfg)
        return

    # 2. Si NO pide un diagrama, se procesa como consulta experta del RETIE con Gemini
    if not GEMINI_KEY:
        await update.message.reply_text("⚠️ Error: La variable GEMINI_API_KEY no está configurada en la terminal.")
        return

    await update.message.reply_chat_action("typing")

    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=PROMPT_SISTEMA_RETIE
        )
        response = model.generate_content(texto_usuario)
        await update.message.reply_text(response.text, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Error en Gemini: {e}")
        await update.message.reply_text(f"❌ Ocurrió un error en el módulo experto RETIE: {str(e)}")


async def _procesar_texto_libre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Manejador intermedio de mensajes de texto en Telegram."""
    if ctx.user_data.get("esperando_rel"):
        ctx.user_data["esperando_rel"] = False
        cfg = ctx.user_data.get("cfg", dict(DEFAULT))
        txt = update.message.text.strip().lower()
        if txt != "listo":
            import re
            for a, b in re.findall(r"(\d{2,6})\s*/\s*(\d{1,4})", txt):
                if int(b) in (1, 5): cfg["rel_tc"] = f"{a}/{b}"
                else: cfg["rel_tp"] = f"{a}/{b}"
        await update.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(update, cfg)
        return
    
    # CORRECCIÓN AQUÍ: Se le pasa el texto del mensaje para procesarlo con Gemini o Matplotlib
    await _procesar_texto(update, update.message.text)


async def _boton(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Manejador de los botones del menú guiado."""
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
        # CORRECCIÓN DE ERROR AQUÍ: Se usa query.edit_message_text en lugar de update.edit_message_text
        await query.edit_message_text("❌ Configuración cancelada.")
        return
        
    if data.startswith("set_"):
        partes = data.split("_")
        k = partes[1]
        v = partes[2]
        if v == "true": v = True
        elif v == "false": v = False
        cfg[k] = v
        ctx.user_data["cfg"] = cfg
        
    if data == "m_rel":
        ctx.user_data["esperando_rel"] = True
        await query.edit_message_text(
            "Escribe las relaciones de transformación en formato `IP/IS`.
"
            "Ejemplo para TC y TP: `200/5 13200/120` o escribe *listo* si ya terminaste.",
            parse_mode="Markdown"
        )
        return
        
    kbd = _menu_kbd(cfg)
    # CORRECCIÓN DE ERROR AQUÍ: Editamos el mensaje usando el objeto query
    await query.edit_message_text(
        "🛠️ *Configurador Guiado de Medida*
Selecciona las opciones técnicas de tu sistema:",
        reply_markup=kbd,
        parse_mode="Markdown"
    )

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
    
    app.add_handler(CallbackQueryHandler(_boton))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _procesar_texto_libre))
    
    print("Bot encendido con éxito. Presiona Ctrl + C para salir.")
    app.run_polling()

if __name__ == "__main__":
    main()
