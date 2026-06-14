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

SIS_TXT = {
    "mono":    "Monofásica",
    "bifasico":"Bifásica",
    "tri3h":   "Trifásica 3H — Aron (2 TC)",
    "tri4h":   "Trifásica 4H — 3 elementos",
}

AYUDA = (
    "⚡ BotElectric\n"
    "Ingeniero de Medida Eléctrica\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📐  /menu          Configurador de diagramas\n"
    "🔍  /clasificar    Tipo de punto de medida 1–5\n"
    "💬  Escríbeme      Consultas normativas\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "Base normativa:\n"
    "  RETIE 2024 · CREG 038/2014 · CREG 015/2014\n\n"
    "Usa /cancelar para reiniciar en cualquier momento."
)

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("/menu"), KeyboardButton("/clasificar")],
     [KeyboardButton("/ayuda"), KeyboardButton("/cancelar")]],
    resize_keyboard=True,
    one_time_keyboard=False,
    input_field_placeholder="Escribe tu consulta eléctrica…"
)

# ── Helpers visuales ──────────────────────────────────────────────────────────
_SAL_LBL = {"conexiones": "Conexiones", "unifilar": "Unifilar", "ambos": "Cx + Uni"}
_SIS_SHORT = {
    "mono":    "Monofásica",
    "bifasico":"Bifásica",
    "tri3h":   "Aron 3H",
    "tri4h":   "Trifásica 4H",
}

def _mini(cfg):
    """Breadcrumb horizontal con los campos seleccionados."""
    p = []
    if cfg.get("tipo"):     p.append(cfg["tipo"].capitalize())
    if cfg.get("sistema"):  p.append(_SIS_SHORT.get(cfg["sistema"], cfg["sistema"]))
    if cfg.get("salida"):   p.append(_SAL_LBL.get(cfg["salida"], cfg["salida"]))
    if cfg.get("norma"):    p.append(cfg["norma"])
    if cfg.get("conexion"): p.append(cfg["conexion"].capitalize())
    inst = cfg.get("instalacion", "")
    if inst == "trafo":
        kva = cfg.get("trafo_kva", "")
        uso = cfg.get("trafo_uso", "")
        s = f"Trafo {kva} kVA".strip() if kva else "Trafo MT"
        if uso: s += f" · {uso}"
        p.append(s)
    elif inst == "barraje":
        t = cfg.get("tension_bt", "")
        p.append(f"Barraje {t} V" if t else "Barraje BT")
    if cfg.get("seccionador"):    p.append(f"Secc. {cfg['seccionador']}")
    if cfg.get("rel_tc"):         p.append(f"TC {cfg['rel_tc']}")
    if cfg.get("rel_tp"):         p.append(f"TP {cfg['rel_tp']}")
    if cfg.get("proteccion_amp"): p.append(f"{cfg['proteccion_amp']} A")
    if cfg.get("calibre_conductor"): p.append(cfg["calibre_conductor"])
    return ("  " + "  ·  ".join(p)) if p else ""

def _dots(n, total=8):
    n = min(max(n, 0), total)
    return "◉" * n + "◯" * (total - n)

def _header(n, cfg, titulo):
    """Cabecera con breadcrumb, barra de progreso y la pregunta actual."""
    sep  = "─────────────────────────"
    mini = _mini(cfg)
    lines = []
    if mini:
        lines += [mini, sep]
    else:
        lines += ["◆ Nuevo diagrama", sep]
    lines += [f"Paso {n}   {_dots(n)}", sep, "", titulo]
    return "\n".join(lines)

def _caption(tipo_diagrama, cfg):
    """Caption enriquecido para la imagen del diagrama."""
    sis   = SIS_TXT.get(cfg.get("sistema", "tri4h"), "Trifásica")
    tipo  = cfg.get("tipo", "indirecta").capitalize()
    norma = cfg.get("norma", "RA8")
    lineas = [
        f"📐 {tipo_diagrama}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔌 {tipo}  ·  {sis}  ·  {norma}",
    ]
    if cfg.get("conexion"):       lineas.append(f"🔁 Conexión: {cfg['conexion'].capitalize()}")
    inst = cfg.get("instalacion","")
    if inst == "trafo":
        kva = cfg.get("trafo_kva",""); uso = cfg.get("trafo_uso","")
        lineas.append(f"🔧 Trafo: {kva} kVA {uso}".strip())
    elif inst == "barraje":
        t_bt = cfg.get("tension_bt","")
        lineas.append(f"🏗️ Barraje: {t_bt} V" if t_bt else "🏗️ Barraje BT")
    if cfg.get("seccionador"):    lineas.append(f"🔀 Seccionador: {cfg['seccionador']} de medida")
    if cfg.get("rel_tc"):         lineas.append(f"🔄 TC: {cfg['rel_tc']}")
    if cfg.get("rel_tp"):         lineas.append(f"📊 TP: {cfg['rel_tp']}")
    if cfg.get("proteccion_amp"): lineas.append(f"🔐 Protección: {cfg['proteccion_amp']} A")
    if cfg.get("calibre_conductor"): lineas.append(f"🔗 Calibre: {cfg['calibre_conductor']}")
    if cfg.get("respaldo"):       lineas.append("👥 Principal + Respaldo")
    lineas += ["━━━━━━━━━━━━━━━━━━━━", "✅ Conforme a CREG 038/2014"]
    return "\n".join(lineas)

# ── Generación de diagramas ────────────────────────────────────────────────────
def _generar(cfg):
    salida = cfg.get("salida", "conexiones")
    out = []
    if salida in ("conexiones", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        diagram_engine.draw_conexiones_retie(cfg, t.name)
        out.append(("Diagrama de Conexiones", t.name))
    if salida in ("unifilar", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        diagram_engine.draw_unifilar_generico(cfg, t.name)
        out.append(("Diagrama Unifilar", t.name))
    return out

async def _enviar_foto(mensaje, cfg):
    await mensaje.reply_chat_action("upload_photo")
    imgs = _generar(cfg)
    for tipo_diagrama, path in imgs:
        with open(path, "rb") as f:
            await mensaje.reply_photo(photo=f, caption=_caption(tipo_diagrama, cfg))
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
        "unifilar","conexiones","esquema","plano","dibuja","grafica","diagrama",
        "directa","semidirecta","indirecta","monofasica","trifasica",
        "monofásica","trifásica",
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
            await update.effective_message.reply_text(
                "⚠️ No pude generar el diagrama.\n\nUsa /menu para configuración guiada."
            )
    else:
        await _consulta_retie(update, texto)

# ── Comandos básicos ──────────────────────────────────────────────────────────
_BIENVENIDA = (
    "⚡ BotElectric\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "Soy tu ingeniero de medida eléctrica.\n"
    "Genero diagramas de conexiones y unifilares\n"
    "conforme a CREG 038/2014 y RETIE 2024.\n\n"
    "  📐 /menu        Configurar un diagrama\n"
    "  🔍 /clasificar  Tipo de punto 1–5\n"
    "  💬 Escríbeme    Consulta normativa\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "¿Comenzamos? Pulsa /menu o escribe tu duda."
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_BIENVENIDA, reply_markup=REPLY_KEYBOARD)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, reply_markup=REPLY_KEYBOARD)

async def cmd_ayuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, reply_markup=REPLY_KEYBOARD)

async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "✓ Listo, reiniciado.\n\nUsa /menu cuando quieras empezar.",
        reply_markup=REPLY_KEYBOARD
    )

async def cmd_diagrama(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = " ".join(ctx.args) if ctx.args else ""
    if not texto:
        await update.message.reply_text(
            "📐 Ejemplo:\n"
            "/diagrama indirecta tri4h CENS 200/5 13200/120\n\n"
            "O usa /menu para configuración guiada."
        )
        return
    await _procesar_texto(update, texto)

# ── /clasificar — Clasificador de punto de medida (CREG 038/2014) ─────────────
async def cmd_clasificar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["clasificando"] = True
    await update.message.reply_text(
        "🔍 Clasificador de punto de medida\n"
        "─────────────────────────\n\n"
        "¿Cuánto es la capacidad instalada?\n\n"
        "  Escribe en MVA:  0.5 · 1 · 30\n"
        "  O en kVA:  500 · 1000 · 5000\n\n"
        "CREG 038/2014, Tabla 1 — Tipos 1 a 5"
    )

async def _hacer_clasificacion(update, txt):
    cleaned = txt.strip().replace(",", ".")
    try:
        valor = float(cleaned)
        if valor <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Escribe solo el número en MVA (ej: 0.5 o 1.5).")
        return

    nota = ""
    if valor > 1000:
        valor = valor / 1000
        nota = f"  ℹ️ Interpreté como kVA → {valor:.3f} MVA\n"

    if valor >= 30:     tipo = 1
    elif valor >= 1:    tipo = 2
    elif valor >= 0.1:  tipo = 3
    elif valor >= 0.01: tipo = 4
    else:               tipo = 5

    EXACTITUD = {
        1: "Medidor 0,2S | TC 0,2S | TP 0,2",
        2: "Medidor 0,5S | TC 0,5S | TP 0,5",
        3: "Medidor 0,5S | TC 0,5S | TP 0,5",
        4: "Medidor Clase 1 | TC 0,5 | TP 0,5",
        5: "Medidor Clase 1 o 2 — sin TC ni TP",
    }
    MANTTO   = {1:"2 años", 2:"4 años", 3:"4 años", 4:"10 años", 5:"10 años"}
    CONEXION = {
        1: "Indirecta (TC + TP) — obligatoria",
        2: "Indirecta (TC + TP) — obligatoria",
        3: "Indirecta (TC + TP) — obligatoria",
        4: "Semidirecta (solo TC) o Directa",
        5: "Directa — sin transformadores de medida",
    }
    RANGO = {
        1: "CI ≥ 30 MVA",
        2: "1 ≤ CI < 30 MVA",
        3: "0,1 ≤ CI < 1 MVA",
        4: "0,01 ≤ CI < 0,1 MVA",
        5: "CI < 0,01 MVA",
    }

    resp = (
        f"🔍 Clasificación del punto\n"
        f"─────────────────────────\n"
        f"{nota}"
        f"\n◆ Tipo {tipo}   ({RANGO[tipo]})\n"
        f"  {valor:.3f} MVA\n\n"
        f"  Exactitud     {EXACTITUD[tipo]}\n"
        f"  Conexión      {CONEXION[tipo]}\n"
        f"  Mantenimiento cada {MANTTO[tipo]}\n\n"
        f"─────────────────────────\n"
        f"CREG 038/2014  Tablas 1 · 2 · 4\n\n"
        f"¿Necesitas el diagrama? → /menu"
    )
    await update.message.reply_text(resp)

# ── Menú guiado v3 ────────────────────────────────────────────────────────────
def _kb(opciones, prefijo):
    btns = [InlineKeyboardButton(txt, callback_data=f"{prefijo}:{val}") for txt, val in opciones]
    return [btns[i:i+2] for i in range(0, len(btns), 2)]

def _validar_numero(txt, nombre):
    cleaned = txt.strip().replace(",", ".")
    try:
        v = float(cleaned)
        if v <= 0:
            return None, f"El valor de {nombre} debe ser positivo (ej: 200)."
        return cleaned, None
    except ValueError:
        return None, f"Valor inválido para {nombre}. Escribe solo el número (ej: 200)."

def _validar_relacion(txt, nombre):
    m = re.match(r"^\s*(\d{2,6})\s*/\s*(\d{1,4})\s*$", txt.strip())
    if not m:
        return None, f"Formato inválido para {nombre}. Escribe como 200/5 o 13200/120."
    return f"{m.group(1)}/{m.group(2)}", None

# ── Helpers de navegación ──────────────────────────────────────────────────────
async def _kb_norma_q(q, cfg, n):
    kb = _kb([("CENS","CENS"),("RA8","RA8")], "norma")
    await q.edit_message_text(
        _header(n, cfg,
                "¿Norma de medida?\n\n"
                "  CENS  empresa de distribución local\n"
                "  RA8   nivel nacional  (OR / STR)"),
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def _kb_norma_msg(msg, cfg, n):
    kb = _kb([("CENS","CENS"),("RA8","RA8")], "norma")
    await msg.reply_text(
        _header(n, cfg,
                "¿Norma de medida?\n\n"
                "  CENS  empresa de distribución local\n"
                "  RA8   nivel nacional  (OR / STR)"),
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def _kb_respaldo_q(q, cfg, n):
    kb = _kb([("Solo principal","no"),("✚  Con respaldo","si")], "respaldo")
    await q.edit_message_text(
        _header(n, cfg,
                "¿Configuración de medidores?\n\n"
                "  Solo principal   un medidor\n"
                "  Con respaldo     principal + chequeo en mismo bloque"),
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def _kb_respaldo_msg(msg, cfg, n):
    kb = _kb([("Solo principal","no"),("✚  Con respaldo","si")], "respaldo")
    await msg.reply_text(
        _header(n, cfg,
                "¿Configuración de medidores?\n\n"
                "  Solo principal   un medidor\n"
                "  Con respaldo     principal + chequeo en mismo bloque"),
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ── cmd_menu ──────────────────────────────────────────────────────────────────
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["cfg"] = dict(DEFAULT)
    ctx.user_data["paso_n"] = 1
    kb = [
        [InlineKeyboardButton("📐   Generar diagrama",    callback_data="inicio:diagramas")],
        [InlineKeyboardButton("💬   Consulta normativa",  callback_data="inicio:consultas")],
    ]
    await update.message.reply_text(
        "⚡ BotElectric\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "¿Qué necesitas hoy?",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ── on_button: máquina de estados completa ────────────────────────────────────
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cfg = ctx.user_data.setdefault("cfg", dict(DEFAULT))
    n   = ctx.user_data.get("paso_n", 1)
    campo, val = q.data.split(":", 1)

    def _adv():
        nonlocal n
        n += 1
        ctx.user_data["paso_n"] = n

    # ── Inicio: Diagramas o Consultas ────────────────────────────────────────
    if campo == "inicio":
        if val == "consultas":
            ctx.user_data["modo_consulta"] = True
            await q.edit_message_text(
                "💬 Consultas normativas\n"
                "─────────────────────────\n\n"
                "Escribe tu pregunta — tengo acceso a:\n"
                "RETIE 2024 · CREG 038/2014 · CREG 015/2014\n\n"
                "  ej: ¿Exactitud de equipos para Tipo 3?\n"
                "  ej: ¿Cuándo es obligatoria la medida indirecta?\n"
                "  ej: Distancias de seguridad tablero BT"
            )
        else:
            _adv()
            kb = _kb([
                ("⬇  Directa",      "directa"),
                ("⚡  Semidirecta",  "semidirecta"),
                ("🔭  Indirecta",   "indirecta"),
            ], "tipo")
            await q.edit_message_text(
                _header(n, cfg,
                        "Tipo de medida:\n\n"
                        "  ⬇  Directa      V e I directos al medidor\n"
                        "  ⚡  Semidirecta  I por TC, tensión directa\n"
                        "  🔭  Indirecta   TC + TP  (media tensión / AT)"),
                reply_markup=InlineKeyboardMarkup(kb)
            )

    # ── Tipo ─────────────────────────────────────────────────────────────────
    elif campo == "tipo":
        cfg["tipo"] = val
        _adv()
        kb = _kb([
            ("📐  Conexiones",  "conexiones"),
            ("📊  Unifilar",    "unifilar"),
            ("📋  Ambos",       "ambos"),
        ], "salida")
        await q.edit_message_text(
            _header(n, cfg,
                    "¿Qué diagrama necesitas?\n\n"
                    "  📐  Conexiones  bloque de pruebas y terminales\n"
                    "  📊  Unifilar   esquema de la instalación\n"
                    "  📋  Ambos      los dos juntos"),
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── Salida ────────────────────────────────────────────────────────────────
    elif campo == "salida":
        cfg["salida"] = val
        _adv()
        tipo = cfg["tipo"]
        incluye_cx = val in ("conexiones", "ambos")

        _kb_sis_dir = _kb([
            ("1φ  Monofásica",  "mono"),
            ("2φ  Bifásica",    "bifasico"),
            ("3φ  Trifásica",   "tri4h"),
        ], "sistema")
        _kb_sis_bi = _kb([
            ("2φ  Bifásica",   "bifasico"),
            ("3φ  Trifásica",  "tri4h" if tipo != "indirecta" else "tri_pend"),
        ], "sistema")
        _kb_inst = _kb([
            ("🔧  Transformador",  "trafo"),
            ("🏗  Barraje BT",    "barraje"),
        ], "instalacion")

        if tipo == "directa":
            if incluye_cx:
                await q.edit_message_text(
                    _header(n, cfg, "¿Sistema eléctrico?"),
                    reply_markup=InlineKeyboardMarkup(_kb_sis_dir)
                )
            else:
                await q.edit_message_text(
                    _header(n, cfg, "¿Punto de conexión?"),
                    reply_markup=InlineKeyboardMarkup(_kb_inst)
                )

        elif tipo == "semidirecta":
            if incluye_cx:
                await q.edit_message_text(
                    _header(n, cfg, "¿Sistema eléctrico?"),
                    reply_markup=InlineKeyboardMarkup(_kb_sis_bi)
                )
            else:
                await q.edit_message_text(
                    _header(n, cfg, "¿Punto de conexión?"),
                    reply_markup=InlineKeyboardMarkup(_kb_inst)
                )

        else:  # indirecta
            if incluye_cx:
                await q.edit_message_text(
                    _header(n, cfg, "¿Sistema eléctrico?"),
                    reply_markup=InlineKeyboardMarkup(_kb_sis_bi)
                )
            else:
                cfg["instalacion"] = "trafo"
                ctx.user_data["esperando_kva"] = True
                await q.edit_message_text(
                    _header(n, cfg, "¿Capacidad del transformador? (kVA)\n\n"
                                    "  Escribe solo el número  ej: 50 o 150")
                )

    # ── Sistema ───────────────────────────────────────────────────────────────
    elif campo == "sistema":
        if val == "tri_pend":
            _adv()
            kb = _kb([
                ("3 Elementos  (9S)",  "tri4h"),
                ("Aron  (5S)",         "tri3h"),
            ], "subtipo")
            await q.edit_message_text(
                _header(n, cfg,
                        "¿Tipo de sistema trifásico?\n\n"
                        "  3 Elementos  3 TC + 3 TP  medidor 9 terminales\n"
                        "  Aron         2 TC + 2 TP  medidor 5 terminales"),
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            cfg["sistema"] = val
            _adv()
            tipo = cfg["tipo"]
            if tipo == "directa" and cfg.get("salida") in ("conexiones", "ambos"):
                kb = _kb([
                    ("↔  Simétrica",   "simetrica"),
                    ("↕  Asimétrica",  "asimetrica"),
                ], "conexion")
                await q.edit_message_text(
                    _header(n, cfg,
                            "¿Conexión del medidor?\n\n"
                            "  ↔  Simétrica   I y V al mismo lado\n"
                            "  ↕  Asimétrica  I y V en lados opuestos"),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            elif tipo == "indirecta":
                cfg["instalacion"] = "trafo"
                ctx.user_data["esperando_kva"] = True
                await q.edit_message_text(
                    _header(n, cfg, "¿Capacidad del transformador? (kVA)\n\n"
                                    "  Escribe solo el número  ej: 50 o 150")
                )
            else:
                kb = _kb([
                    ("🔧  Transformador",  "trafo"),
                    ("🏗  Barraje BT",    "barraje"),
                ], "instalacion")
                await q.edit_message_text(
                    _header(n, cfg,
                            "¿Punto de conexión?\n\n"
                            "  🔧  Transformador  medida en secundario del trafo\n"
                            "  🏗  Barraje BT    medida directo en la barra BT"),
                    reply_markup=InlineKeyboardMarkup(kb)
                )

    # ── Subtipo trifásica (indirecta) ─────────────────────────────────────────
    elif campo == "subtipo":
        cfg["sistema"] = val
        _adv()
        cfg["instalacion"] = "trafo"
        ctx.user_data["esperando_kva"] = True
        await q.edit_message_text(
            _header(n, cfg, "¿Capacidad del transformador? (kVA)\n\n"
                            "  Escribe solo el número  ej: 50 o 150")
        )

    # ── Conexión del medidor (directa) ────────────────────────────────────────
    elif campo == "conexion":
        cfg["conexion"] = val
        _adv()
        kb = _kb([
            ("🔧  Transformador",  "trafo"),
            ("🏗  Barraje BT",    "barraje"),
        ], "instalacion")
        await q.edit_message_text(
            _header(n, cfg,
                    "¿Punto de conexión?\n\n"
                    "  🔧  Transformador  medida en secundario del trafo\n"
                    "  🏗  Barraje BT    medida directo en la barra BT"),
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── Instalación (directa/semidirecta) ────────────────────────────────────
    elif campo == "instalacion":
        cfg["instalacion"] = val
        _adv()
        if val == "trafo":
            kb = _kb([
                ("Exclusivo",   "exclusivo"),
                ("Compartido",  "compartido"),
            ], "trafo_uso")
            await q.edit_message_text(
                _header(n, cfg,
                        "¿El transformador es exclusivo o compartido?\n\n"
                        "  Exclusivo   un solo usuario\n"
                        "  Compartido  varios usuarios / operador de red"),
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            kb = _kb([("🔌  220 V","220"),("⚡  440 V","440")], "tension_bt")
            await q.edit_message_text(
                _header(n, cfg, "¿Tensión del barraje?"),
                reply_markup=InlineKeyboardMarkup(kb)
            )

    # ── Uso del trafo ─────────────────────────────────────────────────────────
    elif campo == "trafo_uso":
        cfg["trafo_uso"] = val
        _adv()
        ctx.user_data["esperando_kva"] = True
        await q.edit_message_text(
            _header(n, cfg, "¿Capacidad del transformador? (kVA)\n\n"
                            "  Escribe solo el número  ej: 50 o 150")
        )

    # ── Tensión del barraje ───────────────────────────────────────────────────
    elif campo == "tension_bt":
        cfg["tension_bt"] = val
        cfg["tension"] = f"{val} V"
        _adv()
        kb = _kb([
            ("✅  Con protección",  "si"),
            ("—  Sin protección",  "no"),
        ], "proteccion")
        await q.edit_message_text(
            _header(n, cfg,
                    "¿Tiene protección aguas abajo?\n\n"
                    "  Breaker o fusible del lado de la carga"),
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── Protección (directa/semidirecta con barraje) ──────────────────────────
    elif campo == "proteccion":
        cfg["tiene_proteccion"] = (val == "si")
        _adv()
        if val == "si":
            ctx.user_data["esperando_prot_amp"] = True
            await q.edit_message_text(
                _header(n, cfg, "¿Amperios de la protección?\n\n"
                                "  Escribe solo el número  ej: 100 o 60")
            )
        else:
            tipo = cfg["tipo"]
            if tipo == "directa":
                await _kb_norma_q(q, cfg, n)
            else:
                ctx.user_data["esperando_rel_tc"] = True
                await q.edit_message_text(
                    _header(n, cfg, "¿Relación de los TCs?\n\n"
                                    "  Formato primario/secundario  ej: 200/5")
                )

    # ── Posición protección (semidirecta) ────────────────────────────────────
    elif campo == "proteccion_pos":
        cfg["proteccion_pos"] = val
        _adv()
        ctx.user_data["esperando_rel_tc"] = True
        await q.edit_message_text(
            _header(n, cfg, "¿Relación de los TCs?\n\n"
                            "  Formato primario/secundario  ej: 200/5")
        )

    # ── Seccionador (indirecta) ───────────────────────────────────────────────
    elif campo == "seccionador":
        cfg["seccionador"] = val
        _adv()
        ctx.user_data["esperando_rel_tc"] = True
        await q.edit_message_text(
            _header(n, cfg, "¿Relación de los TCs?\n\n"
                            "  Formato primario/secundario  ej: 200/5")
        )

    # ── Norma ─────────────────────────────────────────────────────────────────
    elif campo == "norma":
        cfg["norma"] = val
        _adv()
        await _kb_respaldo_q(q, cfg, n)

    # ── Respaldo → confirmación ───────────────────────────────────────────────
    elif campo == "respaldo":
        cfg["respaldo"] = (val == "si")
        _adv()
        await _paso_confirmar(q, cfg)

    # ── Confirmación → generar ────────────────────────────────────────────────
    elif campo == "generar":
        if val == "si":
            await q.edit_message_text("⏳ Generando diagrama…")
            try:
                await _enviar_foto(q.message, cfg)
            except Exception as e:
                log.error(f"Error diagrama: {e}")
                await q.message.reply_text(
                    "⚠️ Error al generar el diagrama.\n"
                    "Usa /menu para volver a intentarlo."
                )
        else:
            ctx.user_data.clear()
            ctx.user_data["cfg"] = dict(DEFAULT)
            ctx.user_data["paso_n"] = 1
            kb = [
                [InlineKeyboardButton("📐   Generar diagrama",   callback_data="inicio:diagramas")],
                [InlineKeyboardButton("💬   Consulta normativa", callback_data="inicio:consultas")],
            ]
            await q.edit_message_text(
                "⚡ BotElectric\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "¿Qué necesitas hoy?",
                reply_markup=InlineKeyboardMarkup(kb)
            )

# ── Pantalla de confirmación ──────────────────────────────────────────────────
async def _paso_confirmar(q, cfg):
    sis   = _SIS_SHORT.get(cfg.get("sistema","tri4h"), "Trifásica")
    tipo  = cfg.get("tipo","indirecta").capitalize()
    norma = cfg.get("norma","RA8")
    sal   = _SAL_LBL.get(cfg.get("salida","conexiones"), "Conexiones")

    lines = [
        "✦ Configuración lista",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  Tipo          {tipo}",
        f"  Sistema       {sis}",
        f"  Diagrama      {sal}",
        f"  Norma         {norma}",
    ]

    if cfg.get("conexion"):
        lines.append(f"  Conexión      {cfg['conexion'].capitalize()}")

    inst = cfg.get("instalacion","")
    if inst or cfg.get("trafo_kva") or cfg.get("tension_bt"):
        lines.append("")
    if inst == "trafo":
        kva = cfg.get("trafo_kva","—"); uso = cfg.get("trafo_uso","")
        s = f"  Transformador  {kva} kVA"
        if uso: s += f"  ·  {uso}"
        lines.append(s)
    elif inst == "barraje":
        t_bt = cfg.get("tension_bt","")
        lines.append(f"  Barraje       {t_bt} V" if t_bt else "  Barraje       BT")

    if cfg.get("tiene_proteccion"):
        pmap = {
            "antes_tc":    "antes del TC",
            "despues_tc":  "después del TC",
            "ambos_tc":    "ambos lados",
            "despues_medidor": "después del medidor",
        }
        pos = pmap.get(cfg.get("proteccion_pos",""), "")
        amp = cfg.get("proteccion_amp","—")
        lines.append(f"  Protección    {amp} A  {('· ' + pos) if pos else ''}".rstrip())

    if cfg.get("seccionador"):
        lines.append(f"  Seccionador   {cfg['seccionador']} de la medida")

    if cfg.get("rel_tc") or cfg.get("rel_tp") or cfg.get("calibre_conductor"):
        lines.append("")
    if cfg.get("rel_tc"):             lines.append(f"  TC            {cfg['rel_tc']}")
    if cfg.get("rel_tp"):             lines.append(f"  TP            {cfg['rel_tp']}")
    if cfg.get("calibre_conductor"):  lines.append(f"  Calibre       {cfg['calibre_conductor']}")

    lines.append("")
    cfg_final = "Principal + Respaldo" if cfg.get("respaldo") else "Solo principal"
    lines.append(f"  Configuración  {cfg_final}")
    lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━"]

    kb = [[
        InlineKeyboardButton("🚀  Generar",  callback_data="generar:si"),
        InlineKeyboardButton("↩  Reiniciar", callback_data="generar:no"),
    ]]
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))

# ── on_text: entradas de texto durante el flujo guiado ───────────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg = ctx.user_data.get("cfg", dict(DEFAULT))
    txt = update.message.text.strip()
    n   = ctx.user_data.get("paso_n", 1)

    # ── Modo consulta (seleccionado desde /menu) ──────────────────────────────
    if ctx.user_data.get("modo_consulta"):
        ctx.user_data["modo_consulta"] = False
        await _consulta_retie(update, txt)
        return

    # ── Clasificador ──────────────────────────────────────────────────────────
    if ctx.user_data.get("clasificando"):
        ctx.user_data["clasificando"] = False
        await _hacer_clasificacion(update, txt)
        return

    # ── kVA del transformador ─────────────────────────────────────────────────
    if ctx.user_data.get("esperando_kva"):
        val_str, err = _validar_numero(txt, "kVA del transformador")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        ctx.user_data["esperando_kva"] = False
        cfg["trafo_kva"] = val_str
        ctx.user_data["cfg"] = cfg
        n += 1; ctx.user_data["paso_n"] = n
        tipo = cfg["tipo"]

        if tipo == "indirecta":
            kb = _kb([
                ("Antes de la medida",   "antes"),
                ("Después de la medida", "despues"),
            ], "seccionador")
            await update.message.reply_text(
                _header(n, cfg,
                        "¿El seccionador está antes o después de la medida?\n\n"
                        "  Antes    lado de red (MT)\n"
                        "  Después  lado de carga (BT)"),
                reply_markup=InlineKeyboardMarkup(kb)
            )
        elif tipo == "directa":
            await _kb_norma_msg(update.message, cfg, n)
        else:
            ctx.user_data["esperando_rel_tc"] = True
            await update.message.reply_text(
                _header(n, cfg, "¿Relación de los TCs?\n\n"
                                "  Formato primario/secundario  ej: 200/5")
            )
        return

    # ── Amperios de protección (directa/semidirecta con barraje) ─────────────
    if ctx.user_data.get("esperando_prot_amp"):
        val_str, err = _validar_numero(txt, "amperios de protección")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        ctx.user_data["esperando_prot_amp"] = False
        cfg["proteccion_amp"] = val_str
        cfg["interruptor"] = f"{val_str} A"
        ctx.user_data["cfg"] = cfg
        n += 1; ctx.user_data["paso_n"] = n
        tipo = cfg["tipo"]

        if tipo == "directa":
            cfg["proteccion_pos"] = "despues_medidor"
            await _kb_norma_msg(update.message, cfg, n)
        else:
            kb = _kb([
                ("Antes del TC",   "antes_tc"),
                ("Después del TC", "despues_tc"),
                ("Ambos lados",    "ambos_tc"),
            ], "proteccion_pos")
            await update.message.reply_text(
                _header(n, cfg,
                        "¿Dónde va la protección respecto a los TCs?"),
                reply_markup=InlineKeyboardMarkup(kb)
            )
        return

    # ── Relación TCs ──────────────────────────────────────────────────────────
    if ctx.user_data.get("esperando_rel_tc"):
        rel, err = _validar_relacion(txt, "relación TC")
        if err:
            await update.message.reply_text(f"⚠️ {err}\n\nEscribe como 200/5:")
            return
        ctx.user_data["esperando_rel_tc"] = False
        cfg["rel_tc"] = rel
        m = re.match(r"^(\d+)/", rel)
        if m: cfg["tc_amp"] = m.group(1)
        ctx.user_data["cfg"] = cfg
        n += 1; ctx.user_data["paso_n"] = n
        tipo = cfg["tipo"]

        if tipo == "indirecta":
            ctx.user_data["esperando_rel_tp"] = True
            await update.message.reply_text(
                _header(n, cfg, "¿Relación de los TPs?\n\n"
                                "  Formato primario/secundario  ej: 13200/120")
            )
        else:
            ctx.user_data["esperando_calibre"] = True
            await update.message.reply_text(
                _header(n, cfg, "¿Calibre del conductor?\n\n"
                                "  ej: AWG 12  ·  #10  ·  4 mm²")
            )
        return

    # ── Relación TPs (indirecta) ──────────────────────────────────────────────
    if ctx.user_data.get("esperando_rel_tp"):
        rel, err = _validar_relacion(txt, "relación TP")
        if err:
            await update.message.reply_text(f"⚠️ {err}\n\nEscribe como 13200/120:")
            return
        ctx.user_data["esperando_rel_tp"] = False
        cfg["rel_tp"] = rel
        ctx.user_data["cfg"] = cfg
        n += 1; ctx.user_data["paso_n"] = n
        # Indirecta → protección (amp)
        ctx.user_data["esperando_prot_amp_ind"] = True
        await update.message.reply_text(
            _header(n, cfg, "¿Amperios de la protección?\n\n"
                            "  Escribe solo el número  ej: 100 o 60")
        )
        return

    # ── Amperios protección indirecta ─────────────────────────────────────────
    if ctx.user_data.get("esperando_prot_amp_ind"):
        val_str, err = _validar_numero(txt, "amperios de protección")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        ctx.user_data["esperando_prot_amp_ind"] = False
        cfg["proteccion_amp"] = val_str
        cfg["interruptor"] = f"{val_str} A"
        ctx.user_data["cfg"] = cfg
        n += 1; ctx.user_data["paso_n"] = n
        # Indirecta → calibre conductor
        ctx.user_data["esperando_calibre"] = True
        await update.message.reply_text(
            _header(n, cfg, "¿Calibre del conductor?\n\n"
                            "  ej: AWG 12  ·  #10  ·  4 mm²")
        )
        return

    # ── Calibre del conductor (semidirecta/indirecta) ─────────────────────────
    if ctx.user_data.get("esperando_calibre"):
        if not txt or len(txt) > 30:
            await update.message.reply_text(
                "⚠️ Escribe el calibre  ej: AWG 12  o  4 mm²"
            )
            return
        ctx.user_data["esperando_calibre"] = False
        cfg["calibre_conductor"] = txt
        ctx.user_data["cfg"] = cfg
        n += 1; ctx.user_data["paso_n"] = n
        await _kb_norma_msg(update.message, cfg, n)
        return

    # ── Texto libre (consulta o diagrama rápido) ──────────────────────────────
    await _procesar_texto(update, update.message.text)

# ── Arranque ──────────────────────────────────────────────────────────────────
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Define BOT_TOKEN antes de iniciar.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("ayuda",      cmd_ayuda))
    app.add_handler(CommandHandler("menu",       cmd_menu))
    app.add_handler(CommandHandler("diagrama",   cmd_diagrama))
    app.add_handler(CommandHandler("clasificar", cmd_clasificar))
    app.add_handler(CommandHandler("cancelar",   cmd_cancelar))
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
