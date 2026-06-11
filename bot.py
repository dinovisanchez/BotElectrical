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
1. Base Normativa Absoluta: Toda respuesta debe alinearse con las exigencias de seguridad, distancias mínimas, grados de protección (IP/IK) y puesta a tierra del RETIE vigente.
2. Cita de Artículos: Siempre que dictamines una exigencia técnica (ej. distancias de seguridad, alturas de medidores), DEBES citar el artículo, sección o tabla del RETIE que lo respalda.
3. Formato Profesional: Utiliza viñetas, negritas para conceptos clave y mantén un lenguaje corporativo y formal de ingeniería en Markdown.
4. Advertencia de Seguridad: Si el usuario te pide algo que viole las distancias de seguridad o ponga en riesgo la instalación según el RETIE, adviértelo inmediatamente usando alertas visibles (⚠️).
"""

def timeout_handler(signum, frame):
    raise TimeoutError("Generacion de diagrama excedio tiempo limite (5s)")

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
    """Devuelve lista de (titulo, ruta_png) segun cfg['salida'].
    Incluye timeout de 5s por diagrama y logging mejorado."""
    salida = cfg.get("salida", "conexiones")
    out = []
    log.debug(f"Generando diagramas: salida={salida}, cfg={cfg}")
    
    try:
        if salida in ("conexiones", "ambos"):
            log.debug("Iniciando diagrama de conexiones...")
            t = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            t.close()
            diagram_engine.draw(cfg, t.name)
            out.append(("Diagrama de conexiones", t.name))
            log.info(f"✓ Conexiones generado en {len(open(t.name, 'rb').read())//1024} KB")
        
        if salida in ("unifilar", "ambos"):
            log.debug("Iniciando diagrama unifilar...")
            t = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            t.close()
            if cfg.get("unifilar_trafo"):
                diagram_engine.draw_unifilar_trafo(cfg, t.name)
            else:
                diagram_engine.draw_unifilar(cfg, t.name)
            out.append(("Diagrama unifilar", t.name))
            log.info(f"✓ Unifilar generado en {len(open(t.name, 'rb').read())//1024} KB")
    except Exception as e:
        log.exception(f"Error en _generar: {e}")
        raise
    
    return out

def _resumen(cfg):
    sis = {"mono":"Monofasica","bifasico":"Bifasica",
           "tri3h":"Trifasica 3 hilos (2 elem.)","tri4h":"Trifasica 4 hilos (3 elem.)"}[cfg["sistema"]]
    txt = f"\U0001F4D0 Medida *{cfg['tipo']}* | {sis} | Norma *{cfg['norma']}*"
    if cfg.get("respaldo"): txt += " | Principal+Chequeo"
    if cfg.get("rel_tc"): txt += f" | RTC {cfg['rel_tc']}"
    if cfg.get("rel_tp"): txt += f" | RTP {cfg['rel_tp']}"
    return txt


def _es_solicitud_diagrama(texto_usuario, entendido):
    texto_lower = texto_usuario.lower()
    diagram_keywords = [
        "unifilar", "conexiones", "medidor", "bloque de prueba", "transformador",
        "kva", "kv", "rtc", "rtp", "interruptor", "respaldo",
        "directa", "semidirecta", "indirecta", "bifasica", "monofasica",
        "trifasica", "cens", "ra8"
    ]
    retie_keywords = [
        "retie", "distancia", "seguridad", "proteccion", "protección",
        "ip", "ik", "tierra", "puesta a tierra", "articulo", "tabla",
        "norma", "requisito", "requisitos", "cumplimiento", "distancias"
    ]

    tiene_diagrama = any(term in texto_lower for term in diagram_keywords)
    tiene_retie = any(term in texto_lower for term in retie_keywords)

    if tiene_diagrama:
        return True
    if tiene_retie and not tiene_diagrama:
        return False
    return bool(entendido)


async def _enviar(update, cfg):
    """Envía los diagramas generados. Con reintentos y logging."""
    try:
        imgs = _generar(cfg)
        if not imgs:
            raise ValueError("No se genero ningun diagrama")
        
        for titulo, path in imgs:
            try:
                file_size = os.path.getsize(path) // 1024
                log.debug(f"Enviando {titulo} ({file_size} KB)...")
                with open(path, "rb") as f:
                    await update.effective_message.reply_photo(
                        photo=f, caption=f"*{titulo}*\n{_resumen(cfg)}", parse_mode="Markdown")
                log.info(f"✓ {titulo} enviado")
            except Exception as e:
                log.error(f"Error enviando {titulo}: {e}")
                raise
            finally:
                try: os.remove(path)
                except OSError: pass
    
    except Exception as e:
        log.exception("Error en _enviar")
        raise

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
    log.info(f"cmd_diagrama: {texto}")
    await _procesar_texto(update, texto)

async def _procesar_texto(update, texto):
    """Procesa texto de usuario: decide entre diagrama y consulta RETIE."""
    texto_usuario = texto.strip()
    log.debug(f"Procesando texto: '{texto_usuario}'")

    cfg, entendido, faltante = parse_spec(texto_usuario)
    pide_diagrama = _es_solicitud_diagrama(texto_usuario, entendido)

    if pide_diagrama:
        try:
            if faltante and cfg.get("tipo") == "indirecta":
                msg = "⚠️ *Campos faltantes pero genero con lo que tengo:* " + ", ".join(faltante)
                await update.effective_message.reply_text(msg, parse_mode="Markdown")
            elif faltante:
                msg = "ℹ️ Recomendacion: agregar " + ", ".join(faltante)
                await update.effective_message.reply_text(msg, parse_mode="Markdown")

            log.info(f"Generando diagramas con cfg: {cfg}")
            await _enviar(update, cfg)
        except ValueError as e:
            log.warning(f"Error en parse_spec: {e}")
            await update.effective_message.reply_text(f"❌ Especificacion invalida: {e}\n\nUsa /ayuda para ver ejemplos.", parse_mode="Markdown")
        except TimeoutError as e:
            log.error(f"Timeout generando diagrama: {e}")
            await update.effective_message.reply_text(f"⏱️ Timeout: diagrama tardo mucho. Intenta con menos elementos o sin respaldo.", parse_mode="Markdown")
        except Exception as e:
            log.exception(f"Error inesperado en _procesar_texto: {e}")
            await update.effective_message.reply_text(f"⚠️ Error: {str(e)[:100]}\n\nContacta al admin si el problema persiste.", parse_mode="Markdown")
        return

    # Si NO pide un diagrama, es una consulta técnica libre sobre RETIE
    if not GEMINI_KEY:
        await update.message.reply_text("⚠️ Error: La variable de entorno GEMINI_API_KEY no está configurada.")
        return

    await update.message.reply_chat_action("typing")
    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=PROMPT_SISTEMA_RETIE
        )
        response = model.generate_content(texto_usuario)
        respuesta_ia = response.text
        await update.message.reply_text(respuesta_ia, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Error con Gemini: {e}")
        await update.message.reply_text(f"❌ Ocurrió un error en el módulo experto: {str(e)}")

# ----------------------------- menu con botones -----------------------------
def _kb(opciones, prefijo):
    btns = [InlineKeyboardButton(txt, callback_data=f"{prefijo}:{val}") for txt, val in opciones]
    return [btns[i:i+2] for i in range(0, len(btns), 2)]

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cfg"] = dict(DEFAULT)
    kb = _kb([("Directa","directa"),("Semidirecta","semidirecta"),("Indirecta","indirecta")], "tipo")
    await update.message.reply_text("1️⃣ Tipo de medida:", reply_markup=InlineKeyboardMarkup(kb))

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Maneja botones del menu."""
    q = update.callback_query
    await q.answer()
    cfg = ctx.user_data.setdefault("cfg", dict(DEFAULT))
    campo, val = q.data.split(":", 1)
    log.debug(f"Menu: {campo}={val}")

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
        
        # Si es DIRECTA: preguntar si asimétrico o simétrico
        if cfg["tipo"] == "directa":
            kb = _kb([("Simétrico","simetrico"),("Asimétrico","asimetrico")], "asimetria")
            await q.edit_message_text("5️⃣ ¿Tipo de conexión?", reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = _kb([("Conexiones","conexiones"),("Unifilar","unifilar"),("Ambos","ambos")], "salida")
            await q.edit_message_text("5️⃣ ¿Que diagrama?", reply_markup=InlineKeyboardMarkup(kb))
    
    elif campo == "asimetria":
        cfg["asimetrico"] = (val == "asimetrico")
        kb = _kb([("Conexiones","conexiones"),("Unifilar","unifilar"),("Ambos","ambos")], "salida")
        await q.edit_message_text("6️⃣ ¿Que diagrama?", reply_markup=InlineKeyboardMarkup(kb))
    
    elif campo == "salida":
        cfg["salida"] = val
        log.info(f"Menu step - tipo={cfg['tipo']}, salida={cfg['salida']}")
        
        # Si es indirecta y salida incluye unifilar: preguntar sobre transformador e interruptores
        if cfg["tipo"] in ("indirecta", "semidirecta") and cfg["salida"] in ("unifilar", "ambos"):
            ctx.user_data["paso_unifilar"] = True
            kb = _kb([("No","no"),("Si","si")], "trafo")
            await q.edit_message_text("7️⃣ ¿Tiene transformador de potencia?", reply_markup=InlineKeyboardMarkup(kb))
        elif cfg["tipo"] == "directa" and cfg["salida"] in ("unifilar", "ambos"):
            # Para directa con unifilar: también preguntar sobre transformador
            ctx.user_data["paso_unifilar"] = True
            kb = _kb([("No","no"),("Si","si")], "trafo")
            await q.edit_message_text("7️⃣ ¿Tiene transformador de potencia?", reply_markup=InlineKeyboardMarkup(kb))
        else:
            # Generar sin más preguntas
            await q.edit_message_text("⏳ Generando...", parse_mode="Markdown")
            if cfg["tipo"] == "indirecta" and not cfg.get("rel_tc"):
                ctx.user_data["esperando_rel"] = True
                await q.edit_message_text(
                    "6️⃣ Envia las relaciones TC y TP (ej. `200/5 13200/120`) "
                    "en un mensaje, o escribe `listo`.", parse_mode="Markdown")
            else:
                await _generar_y_enviar(q, cfg)
    
    elif campo == "trafo":
        cfg["trafo_presente"] = (val == "si")
        if cfg["trafo_presente"]:
            ctx.user_data["esperando_trafo_kva"] = True
            await q.edit_message_text(
                "8️⃣ ¿Cuántos kVA tiene el transformador? (ej. 20, 50, 100)\n"
                "Responde en el siguiente mensaje:", parse_mode="Markdown")
        else:
            # Preguntar sobre interruptor(es)
            kb = _kb([("Antes del medidor","antes"),
                      ("Después del medidor","despues"),
                      ("Ambos (antes y después)","ambos")], "int_pos")
            await q.edit_message_text("8️⃣ ¿Dónde está el/los interruptor(es)?", reply_markup=InlineKeyboardMarkup(kb))
    
    elif campo == "int_pos":
        cfg["interruptor_pos"] = val
        ctx.user_data["esperando_interruptor"] = True
        if val == "ambos":
            await q.edit_message_text(
                "9️⃣ Envía los amperajes de ambos interruptores: ANTES y DESPUÉS\n"
                "(ej. `200A 400A`)", parse_mode="Markdown")
        else:
            label = "Interruptor ANTES" if val == "antes" else "Interruptor DESPUÉS"
            await q.edit_message_text(f"9️⃣ ¿De cuántos Amperios es el {label}? (ej. 200)", parse_mode="Markdown")

async def _generar_y_enviar(update_obj, cfg):
    """Genera y envía diagrama (reutilizable desde menu y texto)."""
    try:
        await update_obj.edit_message_text("⏳ Generando...", parse_mode="Markdown")
        imgs = _generar(cfg)
        for titulo, path in imgs:
            with open(path, "rb") as f:
                await update_obj.effective_message.reply_photo(
                    photo=f, caption=f"*{titulo}*\n{_resumen(cfg)}", parse_mode="Markdown")
            try: os.remove(path)
            except: pass
        log.info(f"✓ Diagrama enviado exitosamente")
    except Exception as e:
        log.exception(f"Error en _generar_y_enviar: {e}")
        await update_obj.effective_message.reply_text(f"❌ Error: {str(e)[:80]}", parse_mode="Markdown")

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Captura relaciones, trafo kVA e interruptores si el menu los espera."""
    cfg = ctx.user_data.get("cfg", dict(DEFAULT))
    txt = update.message.text.strip().lower()
    
    # --- Esperando relaciones TC/TP (para indirecta) ---
    if ctx.user_data.get("esperando_rel"):
        ctx.user_data["esperando_rel"] = False
        log.debug(f"Texto esperado (relaciones): '{txt}'")
        if txt != "listo":
            import re
            for a, b in re.findall(r"\b(\d{2,6})\s*/\s*(\d{1,4})\b", txt):
                if int(b) in (1, 5): cfg["rel_tc"] = f"{a}/{b}"
                else: cfg["rel_tp"] = f"{a}/{b}"
        await update.message.reply_text("⏳ Generando...", parse_mode="Markdown")
        await _generar_y_enviar(update, cfg)
        return
    
    # --- Esperando kVA del transformador ---
    if ctx.user_data.get("esperando_trafo_kva"):
        ctx.user_data["esperando_trafo_kva"] = False
        import re
        m = re.search(r"(\d+(?:[.,]\d+)?)", txt)
        if m:
            cfg["trafo_kva"] = m.group(1).replace(",", ".")
            log.debug(f"Transformador: {cfg['trafo_kva']} kVA")
        
        # Siguiente pregunta: posición del interruptor
        kb = _kb([("Antes del medidor","antes"),
                  ("Después del medidor","despues"),
                  ("Ambos (antes y después)","ambos")], "int_pos")
        await update.message.reply_text("8️⃣ ¿Dónde está el/los interruptor(es)?", 
                                       reply_markup=InlineKeyboardMarkup(kb))
        return
    
    # --- Esperando amperaje del interruptor ---
    if ctx.user_data.get("esperando_interruptor"):
        ctx.user_data["esperando_interruptor"] = False
        import re
        amperes = re.findall(r"(\d+)\s*a(?:mp)?", txt)
        
        if cfg["interruptor_pos"] == "ambos":
            if len(amperes) >= 2:
                cfg["interruptor_antes_kva"] = amperes[0] + " A"
                cfg["interruptor_despues_kva"] = amperes[1] + " A"
                log.debug(f"Interruptores: antes={amperes[0]}A, despues={amperes[1]}A")
        else:
            if amperes:
                if cfg["interruptor_pos"] == "antes":
                    cfg["interruptor_antes_kva"] = amperes[0] + " A"
                else:
                    cfg["interruptor_despues_kva"] = amperes[0] + " A"
                log.debug(f"Interruptor {cfg['interruptor_pos']}: {amperes[0]}A")
        
        await update.message.reply_text("⏳ Generando...", parse_mode="Markdown")
        
        # Si es indirecta y no tiene relaciones, pedirlas ahora
        if cfg["tipo"] == "indirecta" and not cfg.get("rel_tc"):
            ctx.user_data["esperando_rel"] = True
            await update.message.reply_text(
                "6️⃣ Envia las relaciones TC y TP (ej. `200/5 13200/120`) "
                "o escribe `listo`:", parse_mode="Markdown")
        else:
            await _generar_y_enviar(update, cfg)
        return
    
    # --- Texto libre (no del menú) ---
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
    print("Bot encendido con éxito. Presiona Ctrl + C para salir.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
