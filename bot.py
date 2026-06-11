# -*- coding: utf-8 -*-
"""
Bot de Telegram - Ingeniero de diseño eléctrico.
Genera diagramas de CONEXIONES y/o UNIFILAR de sistemas de medida y absuelve consultas RETIE.

Requisitos: python-telegram-bot>=21, matplotlib, google-genai
Variables de entorno: BOT_TOKEN, GEMINI_API_KEY
"""
import os, tempfile, logging, signal
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

import diagram_engine
from parser import parse_spec, DEFAULT

# Configuración estricta de logs para auditoría de la terminal
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("medidor-bot")

# Inicialización nativa y recomendada por el nuevo SDK google-genai
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
client = None
if GEMINI_KEY:
    log.info("Inicializando cliente oficial de Google GenAI...")
    client = genai.Client(api_key=GEMINI_KEY)

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
    
    # Discriminación inteligente de flujo: Palabras clave para activar el motor gráfico de Matplotlib
    palabras_clave_diagrama = ["unifilar", "conexiones", "esquema", "plano", "dibuja", "grafica", "diagrama"]
    
    cfg, entendido, faltante = parse_spec(texto_usuario_limpio)
    
    # Evalúa si la intención primaria es la generación de un esquema gráfico
    pide_diagrama = any(p in texto_minusculas for p in palabras_clave_diagrama) or (entendido and not "retie" in texto_minusculas)
    
    if pide_diagrama:
        log.info(f"Procesando solicitud de diagrama: {texto_usuario_limpio}")
        await update.message.reply_text(_resumen(cfg), parse_mode="Markdown")
        await _enviar(update, cfg)
        return

    # Módulo Experto RETIE con Inteligencia Artificial
    if not client:
        await update.message.reply_text("⚠️ Error de configuración: La variable de entorno GEMINI_API_KEY no está definida en la terminal.")
        return

    await update.message.reply_chat_action("typing")

    try:
        log.info(f"Despachando consulta técnica a la API de Gemini: '{texto_usuario_limpio}'")
        
        # Estructuración agnóstica de prompt: evitamos fallos de serialización inyectando el contexto de manera directa
        prompt_final = f"{PROMPT_SISTEMA_RETIE}\n\nCONSULTA TÉCNICA DEL USUARIO:\n{texto_usuario_limpio}"
        
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt_final
        )
        
        await update.message.reply_text(response.text, parse_mode="Markdown")
        log.info("Respuesta del módulo experto RETIE enviada exitosamente a Telegram.")
        
    except Exception as e:
        log.error(f"Fallo crítico en el módulo Gemini: {e}")
        await update.message.reply_text(f"❌ Ocurrió un error en el módulo experto RETIE: {str(e)}")

async def _procesar_texto_libre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Manejador intermedio de mensajes de texto entrantes."""
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
    """Manejador de los eventos de la interfaz interactiva (botones de Telegram)."""
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

def _menu_kbd(cfg):
    """Genera los botones dinámicos en línea."""
    botones = [
        [InlineKeyboardButton(f"Tipo: {cfg.get('tipo', 'directa')}", callback_data="toggle_tipo")],
        [InlineKeyboardButton("Modificar Relaciones (TC/TP)", callback_data="m_rel")],
        [InlineKeyboardButton("✅ Generar Plano", callback_data="m_listo"),
         InlineKeyboardButton("❌ Cancelar", callback_data="m_cancelar")]
    ]
    return InlineKeyboardMarkup(botones)

def _resumen(cfg):
    return f"📐 *Especificación de Medida Detectada:*\n• Tipo: {cfg.get('tipo')}\n• TC: {cfg.get('rel_tc', 'Directo')}\n• TP: {cfg.get('rel_tp', 'Directo')}"

async def _enviar(update_or_query, cfg):
    """Gestiona la renderización gráfica del diagrama y su envío final por Telegram."""
    msg = update_or_query.message if isinstance(update_or_query, Update) else update_or_query.message
    await msg.reply_chat_action("upload_photo")
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_name = tmp.name
        
        diagram_engine.generar_diagrama(cfg, tmp_name)
        
        with open(tmp_name, "rb") as foto:
            await msg.reply_photo(photo=foto, caption="Aquí tienes tu diagrama de conexiones solicitado. ⚡")
        os.remove(tmp_name)
    except Exception as e:
        log.error(f"Error generando imagen: {e}")
        await msg.reply_text(f"❌ Error al renderizar el gráfico: {str(e)}")

# Manejadores de Comandos Estándar de Telegram
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 ¡Hola! Soy tu asistente de Ingeniería Eléctrica.\n\n• Para planos escrébeme términos como `unifilar` o `conexiones`.\n• Para normativa pregúntame directamente cualquier duda del **RETIE**.")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💡 *Ayuda rápida:*\nEscribe libremente tu pregunta técnica sobre el RETIE (ej: distancias, alturas) o solicita un diagrama indicando el tipo de medida.", parse_mode="Markdown")

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cfg"] = dict(DEFAULT)
    await update.message.reply_text("🛠️ *Configurador Guiado de Medida*\nSelecciona las opciones técnicas de tu sistema:", reply_markup=_menu_kbd(dict(DEFAULT)), parse_mode="Markdown")

async def cmd_diagrama(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Envía los parámetros directamente en un solo texto libre, por ejemplo:\n`indirecta trifasica CENS 200/5`")

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Error Fatal: Define la variable de entorno BOT_TOKEN antes de iniciar.")
    
    app = Application.builder().token(token).build()
    
    # Registro formal de Handlers
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