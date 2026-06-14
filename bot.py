# -*- coding: utf-8 -*-
import os, tempfile, logging, re, asyncio
import httpx
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, KeyboardButton)
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)
import diagram_engine
from parser import parse_spec, DEFAULT

from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("medidor-bot")

GEMINI_KEY   = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

RETIE_STORE_NAME = os.environ.get("RETIE_STORE_NAME", "")

_genai_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

PROMPT_SISTEMA_RETIE = (
    "Eres un asistente tecnico experto en el sector electrico colombiano "
    "(RETIE Resolucion 40117 de 2024 y resoluciones CREG). Respondes consultas "
    "tecnicas de forma estructurada, breve y clara para cualquier nivel de usuario.\n"
    "\n"
    "=== DOCUMENTOS DISPONIBLES PARA BUSQUEDA (RAG) ===\n"
    "- RETIE 2024, Libro 1: Disposiciones Generales (43 pags.) — definiciones, "
    "abreviaturas, gestion de seguridad, analisis de riesgos.\n"
    "- RETIE 2024, Libro 2: Productos (105 pags.) — cajas de medidor (Art. 2.3.4.2), "
    "transformadores (Art. 2.3.32), conductores (Art. 2.3.10), tableros (Art. 2.3.31), "
    "fusibles (Art. 2.3.21), equipos de corte/seccionamiento (Art. 2.3.17).\n"
    "- RETIE 2024, Libro 3: Instalaciones (168 pags.) — niveles de tension (Titulo 9), "
    "distancias de seguridad (Titulo 10), puesta a tierra (Titulo 12), codigo de colores "
    "(Titulo 5), subestaciones (Titulos 22-23), redes de distribucion (Titulo 20), "
    "acometidas (Titulo 26), protecciones (Titulo 27).\n"
    "- RETIE 2024, Libro 4: Evaluacion de la Conformidad (44 pags.) — inspeccion, "
    "certificacion de instalaciones, certificacion de personas, declaraciones de cumplimiento.\n"
    "- CREG 038 de 2018: Autogeneracion en ZNI (documento imagen — busqueda disponible).\n"
    "\n"
    "NOTA: CREG 038/2014 (Codigo de Medida) y CREG 015/2014 NO estan en el store "
    "de busqueda. Responde con los datos memorizados de esas normas (ver abajo).\n"
    "\n"
    "=== DATOS CLAVE MEMORIZADOS — USAR DIRECTAMENTE SIN BUSCAR ===\n"
    "\n"
    "NIVELES DE TENSION (RETIE 2024, Libro 3, Titulo 9, pag. 25):\n"
    "  EAT (Extra Alta):  > 230 kV          (normalizadas: 345 kV, 500 kV)\n"
    "  AT  (Alta):        57,5 kV a 230 kV  (normalizadas: 66, 110, 115, 220, 230 kV)\n"
    "  MT  (Media):       > 1 kV y < 57,5 kV (normalizadas: 11,4 / 13,2 / 34,5 / 44 kV)\n"
    "  BT  (Baja):        <= 1.000 V y >= 25 V c.a. (o >= 60 V c.c.)\n"
    "  MBT (Muy Baja):    < 25 V c.a. / < 50 V c.c.\n"
    "  Frecuencia estandar Colombia: 60 Hz\n"
    "\n"
    "CAJAS DE MEDIDOR — RETIE 2024, Libro 2, Art. 2.3.4.2 (norma NTC 2958):\n"
    "  Hermeticidad:      IP 44 minimo\n"
    "  Resistencia visor: IK 10 (policarbonato) / IK 08 (vidrio templado)\n"
    "  Resistencia cuerpo: IK 09\n"
    "  Visor:             tapa transparente o visor resistente a UV\n"
    "  Envejecimiento UV: 600 h — transmitancia luz >= 79%, amarillez <= 25%\n"
    "  Anticorrosion:     600 h camara salina, progresion <= 2 mm\n"
    "  Materiales:        lamina acero CR, polimérica o hibrida metal-polimerica\n"
    "\n"
    "CODIGO DE COLORES TC/TP — RETIE 2024, Libro 3, Titulo 5:\n"
    "  En sistemas semidirecta e indirecta, el cableado de TC y TP debe "
    "respetar el color de la fase asociada.\n"
    "  Neutro: blanco (o marcado en blanco). Tierra: verde.\n"
    "  No usar blanco ni verde para conductores de fase.\n"
    "\n"
    "CLASIFICACION PUNTOS DE MEDICION (CREG 038/2014, Tabla 1):\n"
    "  Tipo 1: C >= 15.000 MWh/mes  O  CI >= 30 MVA\n"
    "  Tipo 2: 500 <= C < 15.000    O  1 <= CI < 30 MVA\n"
    "  Tipo 3: 50 <= C < 500        O  0,1 <= CI < 1 MVA\n"
    "  Tipo 4: 5 <= C < 50          O  0,01 <= CI < 0,1 MVA\n"
    "  Tipo 5: C < 5 MWh/mes        O  CI < 0,01 MVA\n"
    "  Si CI y C dan tipos distintos: usar el de MAYORES exigencias.\n"
    "  Ejemplo: 500 kVA = 0,5 MVA => Tipo 3 | 1.000 kVA = 1 MVA => Tipo 2\n"
    "\n"
    "TIPOS DE CONEXION (CREG 038/2014):\n"
    "  Directa:     V e I directos al medidor. Sin TC ni TP. BT baja corriente.\n"
    "  Semidirecta: V directo al medidor, I por TC. Sin TP. BT alta corriente.\n"
    "  Indirecta:   V por TP, I por TC. Obligatoria en MT/AT (>1 kV) o CI >= 0,1 MVA.\n"
    "\n"
    "EXACTITUD DE EQUIPOS (CREG 038/2014, Tabla 2):\n"
    "  Tipo 1:    medidor 0,2S | TC 0,2S | TP 0,2\n"
    "  Tipo 2-3:  medidor 0,5S | TC 0,5S | TP 0,5\n"
    "  Tipo 4:    medidor clase 1 | TC 0,5 | TP 0,5\n"
    "  Tipo 5:    medidor clase 1 o 2 | sin TC ni TP\n"
    "\n"
    "FRECUENCIA DE MANTENIMIENTO (CREG 038/2014, Tabla 4):\n"
    "  Tipo 1: cada 2 anos | Tipos 2-3: cada 4 anos | Tipos 4-5: cada 10 anos\n"
    "\n"
    "BLOQUE DE PRUEBAS (CREG 038/2014 y normas CENS/RA8):\n"
    "  Norma CENS:  bornera de 13 terminales, neutro en terminal 11.\n"
    "  Norma RA8:   bornera terminales B1-B26, numeracion 1-10.\n"
    "\n"
    "=== INSTRUCCION PARA BUSQUEDA ===\n"
    "Cuando el usuario haga una pregunta:\n"
    "1. PRIMERO usa los datos memorizados arriba si la respuesta esta ahi.\n"
    "2. LUEGO busca en los documentos indexados para encontrar articulos y paginas "
    "exactas que respalden o complementen la respuesta.\n"
    "3. Cita SIEMPRE con el formato: 'RETIE 2024, Libro X, Titulo Y / Art. Z.W, pag. N'\n"
    "   Ejemplo: 'RETIE 2024, Libro 3, Titulo 9, pag. 25'\n"
    "   Para CREG: 'CREG 038/2014, Tabla N' o 'CREG 038/2014, Art. Z'\n"
    "\n"
    "=== PATRON DE RESPUESTA — OBLIGATORIO EN TODAS LAS RESPUESTAS ===\n"
    "\n"
    "BLOQUE 1 — siempre presente:\n"
    "💬 LO QUE NECESITAS SABER\n"
    "- [max 4 vignetas, lenguaje simple, sin tecnicismos, responde exactamente lo "
    "que preguntaron]\n"
    "\n"
    "BLOQUE 2 — siempre presente:\n"
    "⚙️ ESPECIFICACIONES\n"
    "- [lista o tabla corta: valores, clases de exactitud, distancias, tensiones, etc.]\n"
    "\n"
    "BLOQUE 3 — siempre presente:\n"
    "🏛️ NORMATIVA APLICABLE\n"
    "- [articulos exactos en formato 'RETIE 2024, Libro X, Art. Y, pag. N']\n"
    "\n"
    "BLOQUE 4 — SOLO si el usuario pide recomendacion, consejo o alternativas:\n"
    "✅ TE RECOMENDAMOS\n"
    "- [lista concisa con criterio tecnico-practico]\n"
    "\n"
    "BLOQUE 5 — SOLO si el usuario pide formula, calculo, procedimiento o paso a paso:\n"
    "🧮 DESARROLLO MATEMATICO\n"
    "Paso N - [Nombre del calculo]:\n"
    "   Formula: [simbolos matematicos]\n"
    "   Sustituyendo: [valores reales del problema]\n"
    "   Resultado: [valor con unidades]\n"
    "[Mostrar TODOS los pasos. Cada resultado intermedio aparece antes de usarse.]\n"
    "\n"
    "=== REGLAS ESTRICTAS DE FORMATO ===\n"
    "- NO usar # ni ## ni ### para titulos.\n"
    "- Los 5 titulos de bloque van EXACTAMENTE como estan arriba (emoji + texto).\n"
    "- Cada bloque va separado por UNA linea en blanco.\n"
    "- Titulos en su propia linea, en MAYUSCULAS.\n"
    "- Listas con guion (-), NUNCA con asterisco (*).\n"
    "- SIN asteriscos dobles (**) ni subrayados (__).\n"
    "- SIN links ni URLs.\n"
    "- Numerales como texto plano: 'Art. 2.3.4.2', nunca como link.\n"
    "- MAXIMO 1 linea por vigneta. Prohibidos los parrafos largos.\n"
    "- Emojis dentro de las vignetas para facilitar lectura:\n"
    "    ✅ cumple / correcto  |  ⚠️ advertencia  |  📐 medidas/distancias\n"
    "    🔌 conexiones        |  🏭 equipos       |  📅 plazos/fechas\n"
    "    🎯 clasificaciones   |  💰 costos        |  🔋 energia\n"
)

# UX1: mensaje de bienvenida rediseñado con estructura visual y mención de RETIE (B4)
AYUDA = (
    "⚡ BotElectric — Ingeniero de Medida Eléctrica\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🔌 /menu       Configurar diagrama paso a paso\n"
    "📐 /diagrama   Generar por texto libre\n"
    "   ej: indirecta trifasica CENS 200/5 13200/120\n\n"
    "💬 Consultas normativas — escríbeme directamente:\n"
    "   ej: ¿Clase de exactitud para punto Tipo 3?\n"
    "   ej: Distancias mínimas tablero BT RETIE 2024\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "📋 RETIE 2024 · CREG 038/2014 · CREG 015/2014\n"
    "❌ /cancelar   Reiniciar el asistente"
)

# UX5: teclado persistente de acceso rápido
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("/menu"), KeyboardButton("/diagrama")],
     [KeyboardButton("/ayuda"), KeyboardButton("/cancelar")]],
    resize_keyboard=True,
    one_time_keyboard=False,
    input_field_placeholder="Escribe tu consulta o usa /menu..."
)

# ── Generacion de diagramas ────────────────────────────────────────────────────
def _generar(cfg):
    salida = cfg.get("salida", "conexiones")
    out = []
    if salida in ("conexiones", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        diagram_engine.draw_conexiones_retie(cfg, t.name)
        out.append(("Diagrama de conexiones", t.name))
    if salida in ("unifilar", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        diagram_engine.draw_unifilar_generico(cfg, t.name)
        out.append(("Diagrama unifilar", t.name))
    return out

def _resumen(cfg):
    """UX: resumen visual con emojis estructurado para Telegram."""
    sis = {
        "mono":    "Monofásica",
        "bifasico":"Bifásica",
        "tri3h":   "Trifásica 3 hilos (2 elem.)",
        "tri4h":   "Trifásica 4 hilos (3 elem.)"
    }.get(cfg.get("sistema","tri4h"), "Trifásica")

    lines = [
        f"🔌 Tipo:      {cfg.get('tipo','indirecta').capitalize()}",
        f"⚡ Sistema:   {sis}",
        f"📋 Norma:     {cfg.get('norma','RA8')}",
    ]
    if cfg.get("respaldo"):
        lines.append("👥 Respaldo:  Principal + Chequeo")
    if cfg.get("rel_tc"):
        lines.append(f"🔄 RTC:       {cfg['rel_tc']}")
    if cfg.get("rel_tp"):
        lines.append(f"📊 RTP:       {cfg['rel_tp']}")
    if cfg.get("conexion"):
        lines.append(f"🔗 Conexión:  {cfg['conexion'].capitalize()}")
    if cfg.get("instalacion"):
        lines.append(f"🏭 Instalación: {cfg['instalacion'].capitalize()}")
    if cfg.get("trafo_uso"):
        lines.append(f"   Uso trafo: {cfg['trafo_uso'].capitalize()}")
    if cfg.get("trafo_kva"):
        kva_txt = cfg['trafo_kva']
        tipo_t  = cfg.get('trafo_tipo', '')
        lines.append(f"🔧 Trafo:     {kva_txt} kVA {tipo_t}".rstrip())
    if cfg.get("tc_pos"):
        lines.append(f"⚙️ TC pos.:   {cfg['tc_pos']} del totalizador")
    if cfg.get("tc_amp"):
        lines.append(f"⚙️ TC:        {cfg['tc_amp']} A")
    if cfg.get("proteccion_amp"):
        lines.append(f"🔐 Protección: {cfg['proteccion_amp']} A")
    # G5: solo mostrar interruptor_pos si hay interruptor
    if cfg.get("interruptor"):
        pos = f" ({cfg['interruptor_pos']} del medidor)" if cfg.get("interruptor_pos") else ""
        lines.append(f"🔐 Interruptor: {cfg['interruptor']}{pos}")
    if cfg.get("seccionamiento"):
        lines.append("🔀 Seccionamiento: Sí")
    return "\n".join(lines)

async def _enviar_foto(mensaje, cfg):
    # G6: indicador de actividad antes de la generación (puede tardar 2-8 s)
    await mensaje.reply_chat_action("upload_photo")
    imgs = _generar(cfg)
    for titulo, path in imgs:
        with open(path, "rb") as f:
            await mensaje.reply_photo(
                photo=f,
                caption=f"📐 {titulo}\n\n{_resumen(cfg)}"
            )
        try: os.remove(path)
        except OSError: pass

# ── Modulo experto RETIE ─────────────────────────────────────────────────────
TELEGRAM_MAX_LEN = 4000

async def _enviar_largo(update: Update, texto: str):
    """Envía texto en varios mensajes si excede el límite de Telegram."""
    texto = texto.strip()
    if len(texto) <= TELEGRAM_MAX_LEN:
        await update.message.reply_text(texto)
        return

    partes = []
    restante = texto
    while len(restante) > TELEGRAM_MAX_LEN:
        corte = restante.rfind("\n\n", 0, TELEGRAM_MAX_LEN)
        if corte == -1:
            corte = restante.rfind("\n", 0, TELEGRAM_MAX_LEN)
        if corte == -1:
            corte = restante.rfind(" ", 0, TELEGRAM_MAX_LEN)
        if corte == -1:
            corte = TELEGRAM_MAX_LEN
        partes.append(restante[:corte].strip())
        restante = restante[corte:].strip()
    if restante:
        partes.append(restante)

    for i, parte in enumerate(partes, 1):
        prefijo = f"({i}/{len(partes)})\n" if len(partes) > 1 else ""
        await update.message.reply_text(prefijo + parte)


async def _consulta_retie(update: Update, texto: str):
    if not GEMINI_KEY:
        await update.message.reply_text(
            "⚠️ Consultas normativas no disponibles en este momento.\n"
            "Para diagramas usa /menu."
        )
        return
    await update.message.reply_chat_action("typing")
    try:
        tools = []
        if RETIE_STORE_NAME:
            tools.append(
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[RETIE_STORE_NAME]
                    )
                )
            )

        prompt = f"{PROMPT_SISTEMA_RETIE}\n\nCONSULTA:\n{texto}"

        response = None
        last_err = None
        for intento in range(3):
            try:
                response = await _genai_client.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(tools=tools) if tools else None,
                )
                break
            except Exception as e:
                last_err = e
                msg = str(e)
                if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                    if intento < 2:
                        log.warning(f"Modelo ocupado (intento {intento+1}/3), reintentando...")
                        await asyncio.sleep(2 * (intento + 1))
                        continue
                raise
        if response is None:
            raise last_err

        respuesta = (response.text or "").strip()

        if not respuesta:
            finish_reason = None
            try:
                finish_reason = response.candidates[0].finish_reason
            except Exception:
                pass

            if str(finish_reason) and "RECITATION" in str(finish_reason):
                log.warning("Respuesta bloqueada por RECITATION, reintentando con parafraseo forzado.")
                prompt_retry = (
                    f"{prompt}\n\n"
                    "NOTA: tu intento anterior fue bloqueado por citar texto "
                    "demasiado literal del documento. Responde de nuevo a la "
                    "misma consulta, pero PARAFRASEANDO TODO con tus propias "
                    "palabras (resumenes cortos, sin copiar frases largas "
                    "tal cual del documento), manteniendo las cifras y "
                    "referencias de articulo/numeral/pagina."
                )
                try:
                    response = await _genai_client.aio.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=prompt_retry,
                        config=types.GenerateContentConfig(tools=tools) if tools else None,
                    )
                    respuesta = (response.text or "").strip()
                except Exception as e:
                    log.error(f"Error en reintento por RECITATION: {e}")

        if not respuesta:
            log.warning(f"Respuesta vacia. response={response!r}")
            await update.message.reply_text(
                "⚠️ El modelo no pudo generar una respuesta para esta consulta.\n\n"
                "Intenta dividir la pregunta en partes más específicas."
            )
            return

        respuesta = respuesta.replace("**", "").replace("__", "")
        respuesta = re.sub(r"\[([^\[\]]+)\]\([^\(\)]*\)", r"\1", respuesta)

        if not RETIE_STORE_NAME:
            respuesta += (
                "\n\n⚠️ [Sin acceso al documento RETIE indexado. "
                "Respuesta basada en datos memorizados — verificar con norma oficial.]"
            )

        await _enviar_largo(update, respuesta)

    except Exception as e:
        log.error(f"Error Gemini: {e}")
        msg = str(e)
        if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
            await update.message.reply_text(
                "⏳ El servicio normativo está saturado en este momento.\n"
                "Por favor intenta de nuevo en unos segundos."
            )
        else:
            # UX8: no exponer errores técnicos crudos al usuario
            await update.message.reply_text(
                "⚠️ Ocurrió un error al consultar la normativa.\n\n"
                "Para diagramas usa /menu. Si el error persiste, intenta más tarde."
            )
            log.error(f"Detalle error Gemini: {e}")


async def _procesar_texto(update, texto):
    # G2: parse_spec puede lanzar ValueError — debe capturarse aquí
    try:
        cfg, entendido, faltante = parse_spec(texto)
    except ValueError as e:
        await update.effective_message.reply_text(
            f"⚠️ No pude interpretar la especificación: {e}\n\n"
            "Usa /menu para configuración guiada, o escríbeme algo como:\n"
            "indirecta trifasica CENS 200/5 13200/120"
        )
        return

    palabras_diagrama = [
        "unifilar","conexiones","esquema","plano","dibuja",
        "grafica","diagrama","directa","semidirecta","indirecta",
        "monofasica","trifasica"
    ]
    if any(p in texto.lower() for p in palabras_diagrama):
        if faltante:
            await update.effective_message.reply_text(
                "⚠️ Generando con lo que entendí. Te recomiendo agregar:\n"
                + "\n".join(f"  - {f}" for f in faltante)
            )
        try:
            await _enviar_foto(update.effective_message, cfg)
        except Exception as e:
            log.error(f"Error diagrama: {e}")
            # UX8: mensaje amigable en lugar de stack trace
            await update.effective_message.reply_text(
                "⚠️ No pude generar el diagrama.\n\n"
                "Usa /menu para configuración guiada paso a paso."
            )
    else:
        await _consulta_retie(update, texto)

# ── Comandos ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, reply_markup=REPLY_KEYBOARD)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, reply_markup=REPLY_KEYBOARD)

async def cmd_ayuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, reply_markup=REPLY_KEYBOARD)

# M8: comando /cancelar para reiniciar el flujo en cualquier momento
async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "✅ Asistente reiniciado.\n\n"
        "Usa /menu para un nuevo diagrama o escríbeme tu consulta.",
        reply_markup=REPLY_KEYBOARD
    )

async def cmd_diagrama(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = " ".join(ctx.args) if ctx.args else ""
    if not texto:
        await update.message.reply_text(
            "📐 Ejemplo de uso:\n"
            "/diagrama indirecta tri4h CENS 200/5 13200/120\n\n"
            "O usa /menu para configuración guiada."
        )
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
    # UX4: etiquetas de botones más descriptivas
    kb = _kb([
        ("⬇️ Directa  (sin TC/TP)",  "directa"),
        ("⚡ Semidirecta  (con TC)", "semidirecta"),
        ("🔭 Indirecta  (TC + TP)",  "indirecta")
    ], "tipo")
    await update.message.reply_text(
        "⚡ Configurador de Diagrama\n\n1️⃣ Tipo de medida:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# M3: validación de entrada numérica
def _validar_numero(txt, nombre):
    """Retorna (valor_str, error_msg). error_msg es None si el valor es válido."""
    cleaned = txt.strip().replace(",", ".")
    try:
        v = float(cleaned)
        if v <= 0:
            return None, f"El valor de {nombre} debe ser positivo (ej: 200)."
        return cleaned, None
    except ValueError:
        return None, f"Valor inválido para {nombre}. Escribe solo el número (ej: 200)."


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cfg = ctx.user_data.setdefault("cfg", dict(DEFAULT))
    campo, val = q.data.split(":", 1)

    if campo == "tipo":
        cfg["tipo"] = val
        # UX4: sistema con descripción técnica
        kb = _kb([
            ("1F  Monofásica",               "mono"),
            ("2F  Bifásica",                 "bifasico"),
            ("3H  Trifásica Aron  (2 TC)",   "tri3h"),
            ("4H  Trifásica 3 elem  (3 TC)", "tri4h")
        ], "sistema")
        await q.edit_message_text("2️⃣ Sistema eléctrico:", reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "sistema":
        cfg["sistema"] = val
        kb = _kb([("CENS  (distribuidora local)","CENS"),("RA8  (nacional)","RA8")], "norma")
        await q.edit_message_text("3️⃣ Norma de medida:", reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "norma":
        cfg["norma"] = val
        kb = _kb([("Sin respaldo","no"),("✅ Principal + Chequeo","si")], "respaldo")
        await q.edit_message_text("4️⃣ ¿Medidor de respaldo?", reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "respaldo":
        cfg["respaldo"] = (val == "si")
        kb = _kb([("📐 Conexiones","conexiones"),("📊 Unifilar","unifilar"),("📋 Ambos","ambos")], "salida")
        await q.edit_message_text("5️⃣ ¿Qué diagrama necesitas?", reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "salida":
        cfg["salida"] = val
        if val in ("conexiones", "ambos") and cfg["tipo"] == "directa":
            kb = _kb([
                ("🔁 Simétrica  (americana)", "simetrica"),
                ("↕️ Asimétrica  (europea)",  "asimetrica")
            ], "conexion")
            await q.edit_message_text("6️⃣ Tipo de conexión del medidor:", reply_markup=InlineKeyboardMarkup(kb))
        elif val in ("unifilar", "ambos"):
            await _ir_a_pregunta_instalacion(q, cfg)
        else:
            await _finalizar_o_rel(q, ctx, cfg)

    elif campo == "conexion":
        cfg["conexion"] = val
        if cfg["salida"] in ("unifilar","ambos"):
            await _ir_a_pregunta_instalacion(q, cfg)
        else:
            await _finalizar_o_rel(q, ctx, cfg)

    elif campo == "tipo_instalacion":
        cfg["instalacion"] = val
        tipo = cfg["tipo"]

        if val == "barraje":
            if tipo == "indirecta":
                kb = _kb([("Directo a la red","red"),("Con seccionamiento","seccion")], "conexion_red")
                await q.edit_message_text(
                    "7️⃣ ¿La medida está conectada directo a la red o tiene seccionamiento?",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            elif tipo == "semidirecta":
                kb = _kb([
                    ("Antes del totalizador","antes"),
                    ("Después del totalizador","despues")
                ], "tc_pos")
                await q.edit_message_text(
                    "7️⃣ ¿El TC está antes o después del totalizador principal?",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:  # directa
                kb = _kb([("✅ Sí, tiene breaker","breaker_si"),("No tiene","breaker_no")], "tiene_breaker")
                await q.edit_message_text("7️⃣ ¿Tiene interruptor/breaker de protección?",
                                          reply_markup=InlineKeyboardMarkup(kb))

        else:  # trafo
            if tipo == "indirecta":
                ctx.user_data["esperando_n_trafos"] = True
                await q.edit_message_text(
                    "7️⃣ ¿Cuántos transformadores hay?\n"
                    "Escribe solo el número, ej: 1"
                )
            else:
                kb = _kb([("Exclusivo","exclusivo"),("Compartido","compartido")], "trafo_uso")
                await q.edit_message_text("7️⃣ ¿El transformador es exclusivo o compartido?",
                                          reply_markup=InlineKeyboardMarkup(kb))

    elif campo == "conexion_red":
        cfg["seccionamiento"] = (val == "seccion")
        ctx.user_data["esperando_n_trafos"] = True
        await q.edit_message_text(
            "8️⃣ ¿Cuántos transformadores hay después de la medida?\n"
            "Escribe solo el número, ej: 1"
        )

    elif campo == "tc_pos":
        cfg["tc_pos"] = val
        ctx.user_data["esperando_tc_amp"] = True
        await q.edit_message_text(
            "8️⃣ ¿De cuántos amperios es el TC?\n"
            "Escribe solo el número, ej: 200"
        )

    elif campo == "tiene_breaker":
        if val == "breaker_si":
            kb = _kb([("Antes del medidor","antes"),("Después del medidor","despues")], "breaker_pos")
            await q.edit_message_text("8️⃣ ¿El breaker está antes o después del medidor?",
                                      reply_markup=InlineKeyboardMarkup(kb))
        else:
            cfg["interruptor_pos"] = None
            if cfg["tipo"] == "indirecta":
                ctx.user_data["esperando_rel"] = True
                await q.edit_message_text(
                    "Envía las relaciones TC y TP (ej: 200/5 13200/120)\n"
                    "o escribe listo para omitir."
                )
            else:
                await q.edit_message_text(_resumen(cfg))
                await _enviar_foto(q.message, cfg)

    elif campo == "breaker_pos":
        cfg["interruptor_pos"] = val
        ctx.user_data["esperando_interruptor"] = True
        await q.edit_message_text(
            "9️⃣ ¿De cuántos amperios es el breaker?\n"
            "Escribe solo el número, ej: 100"
        )

    elif campo == "trafo_uso":
        cfg["trafo_uso"] = val
        ctx.user_data["esperando_kva"] = True
        await q.edit_message_text(
            "8️⃣ ¿Cuántos kVA tiene el transformador?\n"
            "Escribe solo el número, ej: 50"
        )

    elif campo == "tipo_trafo":
        cfg["trafo_tipo"] = val
        if cfg["tipo"] == "semidirecta":
            ctx.user_data["esperando_tc_amp"] = True
            await q.edit_message_text(
                "🔟 ¿De cuántos amperios son los TC?\n"
                "Escribe solo el número, ej: 200"
            )
        else:
            kb = _kb([("✅ Sí, tiene breaker","breaker_si"),("No tiene","breaker_no")], "tiene_breaker")
            await q.edit_message_text("9️⃣ ¿Tiene interruptor/breaker de protección?",
                                      reply_markup=InlineKeyboardMarkup(kb))


async def _ir_a_pregunta_instalacion(q, cfg):
    kb = _kb([("🏗️ Barraje","barraje"),("🔧 Transformador","trafo")], "tipo_instalacion")
    await q.edit_message_text(
        "6️⃣ ¿La instalación está conectada a un barraje o a un transformador?",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def _finalizar_o_rel(q, ctx, cfg):
    if cfg["tipo"] == "indirecta":
        ctx.user_data["esperando_rel"] = True
        await q.edit_message_text(
            "Envía las relaciones TC y TP (ej: 200/5 13200/120)\n"
            "o escribe listo para omitir."
        )
    else:
        await q.edit_message_text(_resumen(cfg))
        await _enviar_foto(q.message, cfg)


# ── Manejador de texto (respuestas numéricas y flujo final) ──────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg = ctx.user_data.get("cfg", dict(DEFAULT))
    txt = update.message.text.strip()

    # --- Número de transformadores (INDIRECTA) ---
    if ctx.user_data.get("esperando_n_trafos"):
        # M3: validación numérica
        val_str, err = _validar_numero(txt, "número de transformadores")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        ctx.user_data["esperando_n_trafos"] = False
        n = max(1, int(float(val_str)))
        cfg["n_trafos"] = n
        ctx.user_data["cfg"] = cfg
        ctx.user_data["trafos_kva_lista"] = []
        ctx.user_data["trafos_idx"] = 1
        ctx.user_data["trafos_total"] = n
        ctx.user_data["esperando_kva_lista"] = True
        await update.message.reply_text(f"kVA del transformador 1 de {n}:\nEscribe solo el número, ej: 50")
        return

    # --- kVA de cada transformador (lista, INDIRECTA) ---
    if ctx.user_data.get("esperando_kva_lista"):
        val_str, err = _validar_numero(txt, "kVA del transformador")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        lista = ctx.user_data.get("trafos_kva_lista", [])
        lista.append(val_str)
        ctx.user_data["trafos_kva_lista"] = lista
        idx = ctx.user_data.get("trafos_idx", 1)
        total = ctx.user_data.get("trafos_total", 1)
        if idx < total:
            ctx.user_data["trafos_idx"] = idx + 1
            await update.message.reply_text(f"kVA del transformador {idx+1} de {total}:")
            return
        else:
            ctx.user_data["esperando_kva_lista"] = False
            cfg["trafo_kva"] = " + ".join(lista)
            cfg["trafo_kva_lista"] = lista
            ctx.user_data["cfg"] = cfg
            ctx.user_data["esperando_rel"] = True
            await update.message.reply_text(
                "Ahora envía las relaciones TC y TP de la medida (ej: 200/5 13200/120)\n"
                "o escribe listo para omitir."
            )
            return

    # --- kVA transformador único (SEMIDIRECTA / DIRECTA) ---
    if ctx.user_data.get("esperando_kva"):
        val_str, err = _validar_numero(txt, "kVA del transformador")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        ctx.user_data["esperando_kva"] = False
        cfg["trafo_kva"] = val_str
        ctx.user_data["cfg"] = cfg
        kb = _kb([
            ("Monofásico","monofasico"),
            ("Bifásico","bifasico"),
            ("Trifásico","trifasico")
        ], "tipo_trafo")
        await update.message.reply_text(
            "9️⃣ ¿El transformador es monofásico, bifásico o trifásico?",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # --- Amperios del TC (SEMIDIRECTA) ---
    if ctx.user_data.get("esperando_tc_amp"):
        val_str, err = _validar_numero(txt, "amperios del TC")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        ctx.user_data["esperando_tc_amp"] = False
        cfg["tc_amp"] = val_str
        ctx.user_data["cfg"] = cfg
        if cfg.get("instalacion") == "trafo":
            ctx.user_data["esperando_proteccion"] = True
            await update.message.reply_text(
                "1️⃣1️⃣ ¿De cuántos amperios es la protección (totalizador)?\n"
                "Escribe solo el número, ej: 200"
            )
        else:
            await update.message.reply_text(_resumen(cfg))
            await _enviar_foto(update.message, cfg)
        return

    # --- Amperios de la protección (SEMIDIRECTA + trafo) ---
    if ctx.user_data.get("esperando_proteccion"):
        val_str, err = _validar_numero(txt, "amperios de la protección")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        ctx.user_data["esperando_proteccion"] = False
        cfg["proteccion_amp"] = val_str
        cfg["interruptor"] = f"{val_str} A"
        ctx.user_data["cfg"] = cfg
        await update.message.reply_text(_resumen(cfg))
        await _enviar_foto(update.message, cfg)
        return

    # --- Amperios del breaker/interruptor (DIRECTA) ---
    if ctx.user_data.get("esperando_interruptor"):
        val_str, err = _validar_numero(txt, "amperios del breaker")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        ctx.user_data["esperando_interruptor"] = False
        cfg["interruptor"] = f"{val_str} A"
        ctx.user_data["cfg"] = cfg
        if cfg["tipo"] == "indirecta":
            ctx.user_data["esperando_rel"] = True
            await update.message.reply_text(
                "Envía las relaciones TC y TP (ej: 200/5 13200/120)\n"
                "o escribe listo para omitir."
            )
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
    app.add_handler(CommandHandler("ayuda",    cmd_ayuda))
    app.add_handler(CommandHandler("menu",     cmd_menu))
    app.add_handler(CommandHandler("diagrama", cmd_diagrama))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))   # M8
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot iniciado.")

    webhook_url = os.environ.get("RENDER_EXTERNAL_URL")
    if webhook_url:
        port = int(os.environ.get("PORT", 8443))
        log.info(f"Modo WEBHOOK en {webhook_url} puerto {port}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{webhook_url}/{token}",
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("Modo POLLING (local)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
