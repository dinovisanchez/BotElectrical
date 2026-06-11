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
Variable de entorno:  BOT_TOKEN, GEMINI_API_KEY
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
    """Analiza con precisión si el usuario quiere un plano o una consulta RETIE."""
    texto_usuario_limpio = texto_usuario.strip()
    texto_minusculas = texto_usuario_limpio.lower()
    
    # Discriminación inteligente: Palabras clave obligatorias para activar Matplotlib
    palabras_clave_diagrama = ["unifilar", "conexiones", "esquema", "plano", "dibuja", "grafica", "diagrama"]
    
    cfg, entendido, faltante = parse_spec(texto_usuario_limpio)
    
    # Solo genera diagrama si pide explícitamente gráficos o si el parser entendió pero NO se menciona el RETIE
    pide_diagrama = any(p in texto_minusculas for p in palabras_clave_diagrama) or (entendido and not "retie" in texto_minusculas)
    
    if pide_diagrama:
        log.info(f"Procesando solicitud de diagrama: {texto_usuario_limpio}")
        await update.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(update, cfg)
        return

    # 2. Si es una consulta libre o pregunta por normatividad, se procesa con Gemini
    if not GEMINI_KEY:
        await update.message.reply_text("⚠️ Error: La variable GEMINI_API_KEY no está configurada en la terminal.")
        return

    await update.message.reply_chat_action("typing")

    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=PROMPT_SISTEMA_RETIE
        )
        response = model.generate_content(texto_usuario_limpio)
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
            for a, b in re.findall(r"\b(\d{2,6})\s*/\s*(\d{1,4})\b", txt):
                if int(b) in (1, 5): cfg["rel_tc"] = f"{a}/{b}"
                else: cfg["rel_tp"] = f"{a}/{b}"
        await update.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(update, cfg)
        return
    
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
            "Escribe las relaciones de transformación en formato `IP/IS`.\n"
            "Ejemplo para TC y TP: `200/5 13200/120` o escribe *listo* si ya terminaste.",
            parse_mode="Markdown"
        )
        return
        
    kbd = _menu_kbd(cfg)
    await query.edit_message_text(
        "🛠️ *Configurador Guiado de Medida*\nSelecciona las opciones técnicas de tu sistema:",
        reply_markup=kbd,
        parse_mode="Markdown"
    )

# --- Funciones auxiliares y de Comandos (Personalizables) ---

def _menu_kbd(cfg):
    """Estructura del teclado en línea para el menú guiado."""
    botones = [
        [InlineKeyboardButton(f"Tipo: {cfg.get('tipo', 'directa')}", callback_data="toggle_tipo")],
        [InlineKeyboardButton("Modificar Relaciones (TC/TP)", callback_data="m_rel")],
        [InlineKeyboardButton("✅ Generar Plano", callback_data="m_listo"),
         InlineKeyboardButton("❌ Cancelar", callback_data="m_cancelar")]
    ]
    return InlineKeyboardMarkup(botones)

def _resumen(cfg):
    """Retorna un texto resumen de la configuración técnica."""
    return f"📐 *Especificación de Medida Detectada:*\n• Tipo: {cfg.get('tipo')}\n• TC: {cfg.get('rel_tc', 'Directo')}\n• TP: {cfg.get('rel_tp', 'Directo')}"

async def _enviar(update_or_query, cfg):
    """Genera la imagen con diagramas y la despacha al usuario."""
    msg = update_or_query.message if isinstance(update_or_query, Update) else update_or_query.message
    await msg.reply_chat_action("upload_photo")
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_name = tmp.name
        
        # Llama a tu motor gráfico pasándole la ruta temporal y los parámetros
        diagram_engine.generar_diagrama(cfg, tmp_name)
        
        with open(tmp_name, "rb") as foto:
            await msg.reply_photo(photo=foto, caption="Aquí tienes tu diagrama de conexiones solicitado. ⚡")
        os.remove(tmp_name)
    except Exception as e:
        log.error(f"Error generando imagen: {e}")
        await msg.reply_text(f"❌ Error al renderizar el gráfico: {str(e)}")

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 ¡Hola! Soy tu asistente de Ingeniería Eléctrica.\n\n• Para planos escríbeme términos como `unifilar` o `conexiones`.\n• Para normativa pregúntame directamente cualquier duda del **RETIE**.")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💡 *Ayuda rápida:*\nEscribe libremente tu pregunta técnica sobre el RETIE (ej: distancias, alturas) o solicita un diagrama indicando el tipo de medida.", parse_mode="Markdown")

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cfg"] = dict(DEFAULT)
    await update.message.reply_text("🛠️ *Configurador Guiado de Medida*\nSelecciona las opciones técnicas de tu sistema:", reply_markup=_menu_kbd(dict(DEFAULT)), parse_mode="Markdown")

async def cmd_diagrama(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Envía los parámetros directamente en un solo texto libre, por ejemplo:\n`indirecta trifasica CENS 200/5`")

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