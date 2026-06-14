# -*- coding: utf-8 -*-
import os, tempfile, logging, re, asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# Nombre del File Search Store con el PDF del RETIE (Resolucion 40117 de 2024).
# Se obtiene UNA SOLA VEZ corriendo setup_retie_store.py y pegando el valor aqui.
# Ejemplo: "fileSearchStores/abc123xyz"
RETIE_STORE_NAME = os.environ.get("RETIE_STORE_NAME", "")

_genai_client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

PROMPT_SISTEMA_RETIE = (
    "Eres un asistente tecnico experto en el sector electrico colombiano "
    "(RETIE Resolucion 40117 de 2024 y resoluciones CREG). Tu objetivo es "
    "responder consultas tecnicas de forma extremadamente estructurada, breve "
    "y facil de entender tanto para un cliente sin experiencia como para un "
    "ingeniero.\n"
    "\n"
    "Tienes acceso mediante busqueda en documentos a:\n"
    "- RETIE 2024 (4 libros completos: Disposiciones Generales, Productos, "
    "Instalaciones, Evaluacion de la Conformidad)\n"
    "- CREG 038 de 2014 (Codigo de Medida) - NORMA PRINCIPAL DE MEDICION\n"
    "- CREG 015 de 2014\n"
    "- CREG 038 de 2018 (autogeneracion en ZNI)\n"
    "- Documentos D-019-14 (actualizacion Codigo de Medida)\n"
    "\n"
    "DATOS CLAVE MEMORIZADOS (usar SIEMPRE sin necesidad de buscar):\n"
    "\n"
    "TABLA DE CLASIFICACION DE PUNTOS DE MEDICION (CREG 038/2014, Tabla 1):\n"
    "  Tipo 1: C >= 15.000 MWh-mes  O  CI >= 30 MVA\n"
    "  Tipo 2: 500 <= C < 15.000    O  1 <= CI < 30 MVA\n"
    "  Tipo 3: 50 <= C < 500        O  0,1 <= CI < 1 MVA\n"
    "  Tipo 4: 5 <= C < 50          O  0,01 <= CI < 0,1 MVA\n"
    "  Tipo 5: C < 5 MWh-mes        O  CI < 0,01 MVA\n"
    "  (Si CI y C dan tipos distintos, usar el de MAYORES exigencias)\n"
    "  Ejemplos: 500 kVA=0,5 MVA => Tipo 3 | 1.000 kVA=1 MVA => Tipo 2\n"
    "\n"
    "TIPOS DE CONEXION (CREG 038/2014):\n"
    "  - Directa: V e I directos al medidor. Sin TC ni TP. BT baja corriente.\n"
    "  - Semidirecta: V directo, I por TC. Sin TP. BT alta corriente.\n"
    "  - Indirecta: V por TP, I por TC. Obligatoria en MT/AT (>1 kV) o CI>=0,1 MVA.\n"
    "\n"
    "EXACTITUD DE EQUIPOS (CREG 038/2014, Tabla 2):\n"
    "  Tipo 1: medidor 0,2S | TC 0,2S | TP 0,2\n"
    "  Tipo 2 y 3: medidor 0,5S | TC 0,5S | TP 0,5\n"
    "  Tipo 4: medidor clase 1 | TC 0,5 | TP 0,5\n"
    "  Tipo 5: medidor clase 1 o 2 | sin TC/TP\n"
    "\n"
    "FRECUENCIA MANTENIMIENTO (CREG 038/2014, Tabla 4):\n"
    "  Tipo 1: 2 años | Tipo 2 y 3: 4 años | Tipo 4 y 5: 10 años\n"
    "\n"
    "NIVELES DE TENSION (RETIE 2024, Libro 3, Titulo 9):\n"
    "  BT (Nivel 1): <= 1.000 V | MT (Nivel 2): >1 kV y <57,5 kV | AT: >=57,5 kV\n"
    "  Tensiones MT normalizadas en Colombia: 11,4 / 13,2 / 34,5 / 44 kV\n"
    "\n"
    "CUANDO EL USUARIO HAGA UNA PREGUNTA, BUSCA EN LOS DOCUMENTOS INDEXADOS "
    "para encontrar articulos/numerales/paginas exactos que respalden la respuesta. "
    "Combina lo que encuentres con los datos memorizados arriba.\n"
    "\n"
    "ESTRUCTURA DE RESPUESTA - SIEMPRE estos 3 bloques, en este orden, cortos:\n"
    "\n"
    "1. RESPUESTA DIRECTA (Para el No Experto):\n"
    "   Maximo 3-4 viñetas. Lenguaje simple, sin tecnicismos. Al grano. "
    "Responde exactamente lo que preguntaron.\n"
    "\n"
    "2. ESPECIFICACIONES TECNICAS (Para el Tecnico/Ingeniero):\n"
    "   Tabla simple o lista corta con datos tecnicos clave: clases de "
    "exactitud, distancias, valores, corrientes, tensiones, etc.\n"
    "\n"
    "3. SOPORTE NORMATIVO (Para el Experto/Auditor):\n"
    "   Lista breve con articulos exactos del RETIE o CREG que respaldan "
    "la respuesta. Formato: 'Libro X, Articulo Y, numeral Z, pag. N'\n"
    "\n"
    "BLOQUE ADICIONAL (solo cuando el usuario pida una recomendacion):\n"
    "   RECOMENDACIONES: lista concisa basada en los documentos, con criterio "
    "tecnico-practico.\n"
    "\n"
    "FORMATO DE RESPUESTA - reglas estrictas de presentacion:\n"
    "- NO uses # ni ## ni ### para titulos.\n"
    "- Los bloques van EXACTAMENTE con estos titulos (sin numeros, sin dos puntos extra):\n"
    "    💬 LO QUE NECESITAS SABER\n"
    "    ⚙️ ESPECIFICACIONES\n"
    "    🏛️ NORMATIVA APLICABLE\n"
    "    ✅ TE RECOMENDAMOS  (solo si el usuario pide recomendacion o consejo)\n"
    "- Usa emojis relevantes dentro de cada viñeta para hacer la lectura agradable:\n"
    "    ✅ para lo que cumple o es correcto\n"
    "    ⚠️ para advertencias importantes\n"
    "    📐 para medidas y distancias\n"
    "    🔌 para conexiones electricas\n"
    "    🏭 para equipos e instalaciones\n"
    "    📅 para plazos, fechas y frecuencias\n"
    "    🎯 para clasificaciones o tipos\n"
    "    💰 para costos o valores economicos\n"
    "- Las listas usan guion (-), no asterisco (*).\n"
    "- Sin asteriscos dobles (**). Sin links ni URLs.\n"
    "- Numerales como texto plano (ej: numeral 13.3.1.1), nunca como link.\n"
    "- PROHIBIDO parrafos largos. Maximo 1 linea por viñeta.\n"
    "- Deja UNA linea en blanco entre cada bloque.\n"
    "- El titulo de cada bloque va solo en su linea, en MAYUSCULAS.\n"
    "\n"
    "REGLA ESPECIAL - FORMULAS Y CALCULOS:\n"
    "Si el usuario pide 'la formula', 'como se calcula', 'de donde sale', "
    "'matematicamente', 'el procedimiento', 'paso a paso', 'justifica el calculo', "
    "'explicame el calculo' o cualquier sinonimo, SIEMPRE agrega un bloque extra:\n"
    "\n"
    "    🧮 DESARROLLO MATEMATICO\n"
    "\n"
    "Con este formato para cada paso:\n"
    "    Paso N - Nombre del calculo:\n"
    "    Formula: [simbolos]\n"
    "    Sustituyendo: [valores reales del problema]\n"
    "    Resultado: [valor con unidades]\n"
    "\n"
    "Muestra TODOS los pasos en orden. Cada resultado intermedio debe aparecer "
    "antes de usarse en el siguiente paso."
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
        diagram_engine.draw_conexiones_retie(cfg, t.name)
        out.append(("Diagrama de conexiones", t.name))
    if salida in ("unifilar", "ambos"):
        t = tempfile.NamedTemporaryFile(suffix=".png", delete=False); t.close()
        diagram_engine.draw_unifilar_generico(cfg, t.name)
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
TELEGRAM_MAX_LEN = 4000  # margen bajo el limite real de 4096


async def _enviar_largo(update: Update, texto: str):
    """Envia texto en varios mensajes si excede el limite de Telegram,
    cortando preferentemente en saltos de linea/parrafo."""
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
        await update.message.reply_text("Error: GEMINI_API_KEY no definida.")
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
            try:
                log.warning(f"candidates={response.candidates!r}")
            except Exception:
                pass
            await update.message.reply_text(
                "El modelo no pudo generar una respuesta para esta consulta "
                "(posiblemente por longitud o por las restricciones del "
                "documento). Intenta dividir la pregunta en partes mas "
                "especificas."
            )
            return

        respuesta = respuesta.replace("**", "").replace("__", "")
        # Convierte cualquier link markdown [texto](destino) -> texto, por si el
        # modelo lo genera a pesar de las instrucciones del prompt. El "destino"
        # puede ser una URL con o sin esquema (a veces el modelo genera
        # "[13.3.1.4](13.3.1.4)" o variantes sin "http").
        respuesta = re.sub(r"\[([^\[\]]+)\]\([^\(\)]*\)", r"\1", respuesta)

        if not RETIE_STORE_NAME:
            respuesta += (
                "\n\n[Aviso: RETIE_STORE_NAME no configurado - respondiendo sin "
                "consultar el documento del RETIE. Ver setup_retie_store.py]"
            )

        await _enviar_largo(update, respuesta)
    except Exception as e:
        log.error(f"Error Gemini: {e}")
        msg = str(e)
        if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
            await update.message.reply_text(
                "El modelo esta saturado en este momento (alta demanda en Gemini). "
                "Por favor intenta de nuevo en unos segundos."
            )
        else:
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

    # Si RENDER_EXTERNAL_URL esta definida, usar webhook (modo Render/produccion)
    # Si no, usar polling (modo local/desarrollo)
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
