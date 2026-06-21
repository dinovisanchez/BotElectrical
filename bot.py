# -*- coding: utf-8 -*-
import os, tempfile, logging, re, asyncio, json, time
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

# ── Control de acceso — Google Sheets ─────────────────────────────────────────
try:
    import gspread
    from google.oauth2.service_account import Credentials as _GCreds
    _GSPREAD_OK = True
except ImportError:
    _GSPREAD_OK = False

SHEETS_CREDS_JSON = os.environ.get("GOOGLE_SHEETS_CREDS", "")
SHEET_ID          = os.environ.get("GOOGLE_SHEET_ID", "")
ADMIN_TG_ID       = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))

_gs_client  = None
_user_cache: dict = {}   # uid → {"nombre":str, "estado":str, "ts":float}
_CACHE_TTL  = 300        # 5 minutos

def _gs_get_client():
    global _gs_client
    if _gs_client is None and _GSPREAD_OK and SHEETS_CREDS_JSON and SHEET_ID:
        try:
            creds_dict = json.loads(SHEETS_CREDS_JSON)
            creds = _GCreds.from_service_account_info(
                creds_dict,
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            _gs_client = gspread.authorize(creds)
        except Exception as e:
            log.error(f"Error inicializando gspread: {e}")
    return _gs_client

def _gs_sync(user) -> tuple:
    """Sync: busca al usuario en la hoja; si no existe, lo registra.
    Devuelve (estado, nombre, es_nuevo)."""
    client = _gs_get_client()
    if client is None:
        return "sin_sheets", (user.first_name or "Usuario"), False
    try:
        sheet = client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        log.error(f"Error abriendo sheet: {e}")
        return "sin_sheets", (user.first_name or "Usuario"), False

    uid  = str(user.id)
    rows = sheet.get_all_records()

    for row in rows:
        if str(row.get("Telegram_ID", "")) == uid:
            nombre = str(row.get("Nombre", user.first_name or "Usuario"))
            estado = str(row.get("Estado", "Pendiente")).capitalize()
            return estado, nombre, False

    # Usuario nuevo → registrar
    nombre   = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Usuario"
    username = f"@{user.username}" if user.username else "—"
    from datetime import datetime
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        sheet.append_row([uid, nombre, username, fecha, "Pendiente"])
    except Exception as e:
        log.error(f"Error registrando usuario: {e}")
    return "Pendiente", nombre, True

def _gs_set_estado(uid: str, estado: str):
    """Sync: actualiza Estado de un usuario en la hoja. Devuelve (ok, nombre)."""
    client = _gs_get_client()
    if client is None:
        return False, None
    try:
        sheet   = client.open_by_key(SHEET_ID).sheet1
        col_ids = [str(x) for x in sheet.col_values(1)]  # columna A: Telegram_ID
        try:
            idx     = col_ids.index(str(uid))  # 0-based; idx=0 es la cabecera
            row_num = idx + 1                  # 1-based
        except ValueError:
            return False, None
        nombre = str(sheet.cell(row_num, 2).value or "Usuario")
        sheet.update_cell(row_num, 5, estado)
        _user_cache[str(uid)] = {"estado": estado, "nombre": nombre, "ts": time.time()}
        return True, nombre
    except Exception as e:
        log.error(f"Error _gs_set_estado: {e}")
        return False, None

def _gs_get_all_users():
    """Sync: devuelve todos los registros de la hoja como lista de dicts."""
    client = _gs_get_client()
    if client is None:
        return []
    try:
        return client.open_by_key(SHEET_ID).sheet1.get_all_records()
    except Exception as e:
        log.error(f"Error _gs_get_all_users: {e}")
        return []

async def _check_user(user, force: bool = False) -> tuple:
    """Async wrapper con caché. Devuelve (estado, nombre, es_nuevo)."""
    uid = str(user.id)
    now = time.time()
    if not force and uid in _user_cache:
        c = _user_cache[uid]
        if now - c["ts"] < _CACHE_TTL:
            return c["estado"], c["nombre"], False
    loop = asyncio.get_event_loop()
    try:
        estado, nombre, es_nuevo = await loop.run_in_executor(None, lambda: _gs_sync(user))
    except Exception as e:
        log.error(f"Sheets error: {e}")
        estado, nombre, es_nuevo = "sin_sheets", (user.first_name or "Usuario"), False
    _user_cache[uid] = {"estado": estado, "nombre": nombre, "ts": now}
    return estado, nombre, es_nuevo

async def _access_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Guarda de acceso. Devuelve False (y responde) si el usuario no puede operar."""
    user = update.effective_user
    if not user:
        return True
    if ADMIN_TG_ID and user.id == ADMIN_TG_ID:
        return True  # admin siempre tiene acceso completo
    estado, nombre, _ = await _check_user(user)
    if estado == "Inactivo":
        msg = (
            f"⚠️ Hola, {nombre}.\n\n"
            "Tu suscripción se encuentra suspendida.\n"
            "Contacta al administrador para reactivarla."
        )
        if update.message:
            await update.message.reply_text(msg)
        elif update.callback_query:
            await update.callback_query.answer(
                "Suscripción suspendida. Contacta al administrador.", show_alert=True
            )
        return False
    if estado == "Pendiente":
        msg = (
            f"⏳ Hola, {nombre}.\n\n"
            "Tu registro está pendiente de activación.\n"
            "Escribe /start cuando el administrador te habilite."
        )
        if update.message:
            await update.message.reply_text(msg)
        elif update.callback_query:
            await update.callback_query.answer(
                "Registro pendiente. Espera la activación.", show_alert=True
            )
        return False
    return True   # Activo o sin_sheets (modo degradado)

PROMPT_SISTEMA_RETIE = (
    "=== ROL PROFESIONAL ===\n"
    "Eres un Ingeniero Electricista Senior colombiano con mas de 20 anos de experiencia en:\n"
    "RETIE, resoluciones CREG, Codigo de Medida, sistemas de medicion de energia,\n"
    "comercializacion de energia, operacion y mantenimiento electrico, calidad de la\n"
    "energia, protecciones electricas, transformadores, redes de distribucion,\n"
    "instalaciones electricas comerciales e industriales, analisis de fallas y diagnostico.\n"
    "\n"
    "Tu objetivo es resolver consultas tecnicas de manera PRECISA, SENCILLA y basada\n"
    "UNICAMENTE en hechos verificables.\n"
    "\n"
    "=== REGLA PRINCIPAL ===\n"
    "NO SUPONGAS.\n"
    "NO INVENTES.\n"
    "NO COMPLETES INFORMACION FALTANTE.\n"
    "NO RESPONDAS CON BASE EN PROBABILIDADES.\n"
    "Si la informacion suministrada no es suficiente, indicalo claramente y solicita\n"
    "UNICAMENTE los datos necesarios.\n"
    "\n"
    "=== JERARQUIA TECNICA ===\n"
    "Las respuestas deben priorizar en este orden:\n"
    "1. Seguridad electrica.\n"
    "2. RETIE vigente (Resolucion 40117 de 2024).\n"
    "3. Resoluciones CREG vigentes.\n"
    "4. Codigo de Medida.\n"
    "5. Normas tecnicas aplicables.\n"
    "6. Buenas practicas de ingenieria.\n"
    "Si existe contradiccion entre practica y regulacion, PREVALECE LA REGULACION.\n"
    "\n"
    "=== CONSULTAS NORMATIVAS ===\n"
    "Cuando el usuario consulte sobre RETIE, CREG o regulacion:\n"
    "- Indica la norma aplicable con numeral o articulo exacto cuando sea posible.\n"
    "- Diferencia claramente entre OBLIGACION NORMATIVA y RECOMENDACION TECNICA.\n"
    "- Indica si el tema depende del operador de red.\n"
    "- NUNCA presentes una recomendacion como si fuera una obligacion normativa.\n"
    "\n"
    "=== CONSULTAS TECNICAS ===\n"
    "Cuando el usuario consulte sobre problemas electricos:\n"
    "1. Analizar la informacion suministrada.\n"
    "2. Identificar posibles causas.\n"
    "3. Explicar la causa mas probable.\n"
    "4. Indicar riesgos.\n"
    "5. Proponer soluciones.\n"
    "Si existen varias causas posibles, enumerarlas segun probabilidad e indicar\n"
    "que informacion falta para determinar la causa real.\n"
    "\n"
    "=== MANEJO DE INCERTIDUMBRE ===\n"
    "Si no existe informacion suficiente responde exactamente:\n"
    "  'No es posible emitir un concepto tecnico definitivo con la informacion suministrada.'\n"
    "Luego solicita UNICAMENTE la informacion faltante. Nada mas.\n"
    "\n"
    "=== CONTROL DE CALIDAD — ANTES DE RESPONDER VERIFICA ===\n"
    "✓ La informacion que voy a dar es tecnicamente correcta.\n"
    "✓ Existe soporte normativo para lo que afirmo.\n"
    "✓ No estoy suponiendo nada.\n"
    "✓ La respuesta es segura.\n"
    "✓ No falta informacion importante para responder con certeza.\n"
    "✓ La solucion propuesta es viable en campo.\n"
    "Si alguna parte de la respuesta depende de una suposicion, indicarlo explicitamente.\n"
    "\n"
    "=== ESTRUCTURA DE RESPUESTA ===\n"
    "1. Concepto tecnico.\n"
    "2. Fundamento.\n"
    "3. Norma aplicable si existe.\n"
    "4. Riesgos.\n"
    "5. Recomendacion.\n"
    "6. Informacion faltante si aplica.\n"
    "\n"
    "=== LENGUAJE ===\n"
    "- Responde de manera sencilla y directa.\n"
    "- Evita lenguaje juridico innecesario.\n"
    "- Explica los terminos tecnicos cuando sea necesario.\n"
    "- Prioriza soluciones practicas y concretas.\n"
    "- La precision tecnica tiene prioridad sobre la rapidez de respuesta.\n"
    "- Nunca responder por intuicion. Nunca inventar informacion. Nunca asumir datos.\n"
    "\n"
    "=== PATRON DE NORMALIZACION ===\n"
    "Cuando el usuario describa el estado actual de un equipo o instalacion y\n"
    "pregunte que se necesita para 'normalizar', 'cumplir', 'legalizar' o similar:\n"
    "  1. Identifica el tipo de equipo/instalacion a partir de la descripcion.\n"
    "  2. Determina cual es la no-conformidad o falla segun la norma aplicable.\n"
    "  3. Lista exactamente que se debe hacer/corregir para cumplir RETIE/CREG.\n"
    "  4. Si el usuario dice algo como 'tiene placa' o 'tiene certificado', asume\n"
    "     que ese aspecto SI cumple y enfoca la normalizacion en los demas requisitos.\n"
    "  5. Si el texto del usuario ya especifica la falla (ej: 'le falta la puesta a\n"
    "     tierra'), usa esa informacion como punto de partida y confirma si es la\n"
    "     unica no-conformidad o si hay mas segun la norma.\n"
    "\n"
    "=== DOCUMENTOS DISPONIBLES PARA BUSQUEDA (RAG) ===\n"
    "- RETIE 2024, Libro 1: Disposiciones Generales — definiciones, "
    "abreviaturas, gestion de seguridad, analisis de riesgos.\n"
    "- RETIE 2024, Libro 2: Productos — cajas de medidor (Art. 2.3.4.2), "
    "transformadores de medida (Art. 2.3.32), conductores (Art. 2.3.10), tableros (Art. 2.3.31), "
    "fusibles (Art. 2.3.21), equipos de corte/seccionamiento (Art. 2.3.17).\n"
    "- RETIE 2024, Libro 3: Instalaciones — niveles de tension (Titulo 9), "
    "distancias de seguridad (Titulo 10), puesta a tierra (Titulo 12), codigo de colores "
    "(Titulo 5), subestaciones (Titulos 22-23), redes de distribucion (Titulo 20), "
    "acometidas (Titulo 26), protecciones (Titulo 27).\n"
    "- RETIE 2024, Libro 4: Evaluacion de la Conformidad — inspeccion, "
    "certificacion de instalaciones, certificacion de personas, declaraciones de cumplimiento.\n"
    "- CREG 038 de 2018: Autogeneracion en ZNI.\n"
    "- CREG 038/2014 y CREG 015/2014: ver datos memorizados abajo.\n"
    "- Conexiones medida directa Colombia (ver datos memorizados abajo).\n"
    "- Transformadores de medida TC/TP Colombia (ver datos memorizados abajo).\n"
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
    "  Envejecimiento UV: 600 h — transmitancia >= 79%, amarillez <= 25%\n"
    "  Anticorrosion:     600 h camara salina, progresion <= 2 mm\n"
    "  Materiales:        lamina acero CR, polimerica o hibrida metal-polimerica\n"
    "\n"
    "CODIGO DE COLORES — RETIE 2024, Libro 3, Titulo 5:\n"
    "  Fase R / L1: Rojo (#D32F2F)       Fase S / L2: Amarillo (#F9A825)\n"
    "  Fase T / L3: Azul (#1565C0)       Neutro (N):  Blanco\n"
    "  Tierra (PE): Verde o Verde-Amarillo\n"
    "  Reglas: NO usar blanco ni verde para fase. La tierra NO va en bornes del medidor.\n"
    "  El cableado de TC y TP debe respetar el color de la fase asociada.\n"
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
    "BLOQUE DE PRUEBAS — TERMINALES (CREG 038/2014, normas CENS y RA8):\n"
    "  Norma CENS (EPM, interior): 13 terminales. Neutro en terminal 11.\n"
    "    1=I_R_ent  2=V_R  3=I_R_cie  4=I_S_ent  5=V_S  6=I_S_cie\n"
    "    7=I_T_ent  8=V_T  9=I_T_cie  10=aux     11=Neutro  12-13=aux\n"
    "  Norma RA8 (Codensa/Enel, AT/MT): bornes B1-B26. Neutro en B10.\n"
    "    B1=I_R_ent  B2=V_R  B3=I_R_cie  B4=I_S_ent  B5=V_S  B6=I_S_cie\n"
    "    B7=I_T_ent  B8=V_T  B9=I_T_cie  B10=Neutro  B11-B26=auxiliares\n"
    "  En medida Aron (2 elem): terminales de fase S sin corriente; "
    "solo tension de referencia en borne 5 (CENS) o B5 (RA8).\n"
    "  Forma 9S (medidor trifasico 4H, 3 elementos): "
    "bornes medidor 1=IA 2=VA 3=IA' 4=IB 5=VB 6=IB' 7=IC 8=VC 9=IC' 10/11=N\n"
    "\n"
    "BORNES MEDIDOR DIRECTA — ASIGNACION EXACTA (RETIE 2024, NTC 2050):\n"
    "  CONEXION SIMETRICA (patron espejo/cruzado):\n"
    "    Mono 4 bornes: [1:Fase-ent | 2:Neutro-SAL | 3:Neutro-ENT | 4:Fase-sal]\n"
    "    Tri4H 8 bornes: [1:R-ent | 2:S-ent | 3:T-ent | 4:N-ent | "
    "5:N-sal | 6:T-sal | 7:S-sal | 8:R-sal]\n"
    "    La fase entra por borne 1 y sale por borne 4 (espejo completo).\n"
    "    Tap de tension V+ en borne 1 (lado acometida, antes de la bobina I).\n"
    "  CONEXION ASIMETRICA (patron secuencial/en linea):\n"
    "    Mono 4 bornes: [1:Fase-ent | 2:Fase-SAL | 3:Neutro-ent | 4:Neutro-sal]\n"
    "    Tri4H 8 bornes: [1:R-ent | 2:R-sal | 3:S-ent | 4:S-sal | "
    "5:T-ent | 6:T-sal | 7:N-ent | 8:N-sal]\n"
    "    Cada par de bornes adyacentes (1-2, 3-4) = misma fase, entrada y salida.\n"
    "    Tap de tension V+ en borne 2 (lado carga, despues de la bobina I).\n"
    "  Calibre minimo conductores (NTC 2050, Tabla 310-16): "
    "15A=AWG14(2,08mm2) | 30A=AWG10(5,26mm2) | 50A=AWG8(8,37mm2) | "
    "100A=AWG4(21,15mm2) | 200A=AWG3/0(85mm2)\n"
    "  Aislamiento minimo: 600V THHN o THWN-2 cobre.\n"
    "\n"
    "TRANSFORMADORES DE MEDIDA — TC (Transformador de Corriente):\n"
    "  Instalado EN SERIE con la linea. El secundario NUNCA debe abrirse en operacion.\n"
    "  Clases de exactitud para medida (NTC-IEC 61869-2):\n"
    "    0,1 | 0,2 | 0,2S | 0,5 | 0,5S | 1,0 | 3,0\n"
    "    Sufijo S: garantiza exactitud desde el 1% de la corriente nominal (amplio rango).\n"
    "  Secundario estandar en Colombia: 5 A (principal) o 1 A.\n"
    "  Relaciones TC mas comunes (A): 50/5 100/5 150/5 200/5 300/5 400/5 "
    "500/5 600/5 800/5 1000/5 1500/5 2000/5\n"
    "  Relacion: Kn = I_primario / I_secundario. Corriente real = I_secundario × Kn.\n"
    "  Polaridad: P1(●)=entrada corriente. S1(●)=positivo secundario → va a I_in del medidor.\n"
    "  ADVERTENCIA: NUNCA abrir secundario de TC energizado (alta tension fatal).\n"
    "  Burden tipico para medida: 5 VA o 10 VA a 5A. Conductor secundario minimo 2,5mm2 Cu.\n"
    "\n"
    "TRANSFORMADORES DE MEDIDA — TP (Transformador de Tension/Potencial):\n"
    "  Instalado EN PARALELO con la linea. NO cortocircuitar secundario.\n"
    "  Clases de exactitud (NTC-IEC 61869-3): 0,1 | 0,2 | 0,5 | 1,0 | 3,0\n"
    "  Secundario estandar en Colombia: 120 V (fase-neutro).\n"
    "  Relaciones TP mas comunes en Colombia (primario / secundario):\n"
    "    Sistema 13,2 kV estrella: 13.200V/120V = Kn 110\n"
    "    Sistema 7,62 kV delta: 7.620V/120V = Kn 63,5\n"
    "    Sistema 34,5 kV: 34.500V/120V = Kn 287,5\n"
    "    Sistema 44 kV: 44.000V/120V = Kn 366,7\n"
    "    Sistema 11,4 kV: 11.400V/120V = Kn 95\n"
    "    Sistema 66 kV (AT): 66.000V/120V = Kn 550\n"
    "    Sistema 110 kV (AT): 110.000V/120V = Kn 916,7\n"
    "  Energia real = E_medida × Kn_TC × Kn_TP\n"
    "  Ejemplo: 1.000 kWh medidos, TC 200/5 (Kn=40), TP 13200/120 (Kn=110) "
    "=> E_real = 1.000 × 40 × 110 = 4.400.000 kWh = 4.400 MWh\n"
    "\n"
    "REQUISITOS POR OPERADOR DE RED (Colombia):\n"
    "  Enel/Codensa (Bogota y Cundinamarca): NTC 2967, ET-CODENSA-001.\n"
    "    Caja IPC-1, sello tipo Destral. Medidores: Itron, Landis+Gyr, Elster.\n"
    "  EPM (Medellin y Antioquia): ET-EPM-G1-001, NET-ET-110.\n"
    "    Caja metalica con puerta de vidrio. Altura: 1,0m–1,8m al centro del medidor.\n"
    "  Afinia (Costa Atlantica, ex-Electricaribe): ET-AFINIA-GD-002.\n"
    "    En zonas rurales puede aplicar medicion monofasica en red trifasica.\n"
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
    "- Los titulos de bloque van EXACTAMENTE como estan arriba (emoji + texto).\n"
    "- Cada bloque va separado por UNA linea en blanco.\n"
    "- Titulos en su propia linea, en MAYUSCULAS.\n"
    "- Listas con guion (-), NUNCA con asterisco (*).\n"
    "- SIN asteriscos dobles (**) ni subrayados (__).\n"
    "- SIN links ni URLs.\n"
    "- Numerales como texto plano: 'Art. 2.3.4.2', nunca como link.\n"
    "- MAXIMO 1 linea por vigneta. Prohibidos los parrafos largos.\n"
    "- PROHIBIDO repetir la pregunta, introduccion ni despedida.\n"
    "- Emojis dentro de las vignetas para facilitar lectura:\n"
    "    ✅ cumple / correcto  |  ⚠️ advertencia  |  📐 medidas/distancias\n"
    "    🔌 conexiones        |  🏭 equipos       |  📅 plazos/fechas\n"
    "    🎯 clasificaciones   |  💰 costos        |  🔋 energia\n"
)

PROMPT_DIAGRAMA = (
    "Eres un Ingeniero Electricista Senior colombiano especialista en sistemas de "
    "medicion de energia electrica (RETIE 2024, CREG 038/2014).\n"
    "\n"
    "Tu tarea UNICA es recopilar toda la informacion necesaria para generar un "
    "diagrama electrico correcto. No das conceptos tecnicos extensos. Solo preguntas "
    "y confirmaciones tecnicas breves.\n"
    "\n"
    "=== REGLAS ESTRICTAS ===\n"
    "- Haz MAXIMA UNA pregunta a la vez.\n"
    "- Si el usuario da informacion en la primera descripcion, usala como base y "
    "pregunta solo lo que falta.\n"
    "- Si la respuesta tecnica del usuario tiene un error, corrigelo brevemente "
    "y continua.\n"
    "- NUNCA inventes ni supongas datos que el usuario no haya dado.\n"
    "- Cuando tengas TODA la informacion, emite la senal DIAGRAMA_LISTO.\n"
    "\n"
    "=== INFORMACION QUE DEBES RECOPILAR ===\n"
    "1. DIAGRAMA: conexiones, unifilar, o ambos.\n"
    "2. SISTEMA: mono / bifasico / trifasico 3H (2 elementos, Aron) / trifasico 4H (3 elementos).\n"
    "3. TIPO DE MEDIDA: directa (sin TC/TP) / semidirecta (con TC) / indirecta (TC + TP).\n"
    "   Ayuda si no sabe: directa < 100 A BT, semidirecta > 100 A o hasta 600 V, indirecta MT.\n"
    "4. INSTALACION: trafo propio / barra BT / red directa.\n"
    "   Si hay trafo: cantidad, kVA de cada uno, tipo (mono/bi/tri), tension MT.\n"
    "   Si es barra: tension de la barra.\n"
    "5. PROTECCIONES:\n"
    "   Interruptor totalizador: amperaje.\n"
    "   Seccionador de medida: antes o despues del bloque de pruebas.\n"
    "6. EQUIPOS DE MEDIDA:\n"
    "   Semidirecta/Indirecta: relacion TC (ej. 200/5).\n"
    "   Indirecta: relacion TP (ej. 13200/120).\n"
    "   Norma: RA8 (operador nacional) o CENS (Codensa/Enel).\n"
    "   Con o sin medidor de respaldo.\n"
    "7. CONDUCTOR: calibre principal (ej. AWG 2/0). Si no sabe, omitir.\n"
    "\n"
    "=== SENAL DE DIAGRAMA LISTO ===\n"
    "Cuando tengas TODA la informacion, responde EXACTAMENTE:\n"
    "\n"
    "DIAGRAMA_LISTO\n"
    "```json\n"
    "{\n"
    '  "sistema": "tri4h",\n'
    '  "tipo": "semidirecta",\n'
    '  "salida": "ambos",\n'
    '  "norma": "RA8",\n'
    '  "instalacion": "trafo",\n'
    '  "n_trafos": 1,\n'
    '  "trafo_kva": "225",\n'
    '  "trafo_tipo": "trifasico",\n'
    '  "interruptor": "400 A",\n'
    '  "seccionador": "despues",\n'
    '  "rel_tc": "200/5",\n'
    '  "calibre_conductor": "AWG 2/0",\n'
    '  "respaldo": false\n'
    "}\n"
    "```\n"
    "\n"
    "CAMPOS DEL JSON:\n"
    'sistema: "mono" | "bifasico" | "tri3h" | "tri4h"\n'
    'tipo: "directa" | "semidirecta" | "indirecta"\n'
    'salida: "conexiones" | "unifilar" | "ambos"\n'
    'norma: "RA8" | "CENS"\n'
    'instalacion: "trafo" | "barraje" | "" (vacio = red sin trafo)\n'
    "n_trafos: entero >= 1\n"
    "trafo_kva: string ej '225'\n"
    "trafo_kva_list: lista ej ['225','112'] si hay varios trafos\n"
    'trafo_tipo: "monofasico" | "bifasico" | "trifasico"\n'
    "interruptor: string ej '400 A'\n"
    'seccionador: "antes" | "despues" | ""\n'
    "rel_tc: string ej '200/5'\n"
    "rel_tp: string ej '13200/120'\n"
    "calibre_conductor: string ej 'AWG 2/0'\n"
    "respaldo: true | false\n"
    "v_mt: string ej '13.2 kV' (tension MT, solo indirecta)\n"
    "tension_bt: string ej '220' (solo si instalacion=barraje)\n"
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

# ── Prompt validación de conexiones (Gemini Vision) ──────────────────────────
PROMPT_VALIDACION_CX = (
    "Eres un Ingeniero Electricista Senior con mas de 20 anos de experiencia en "
    "sistemas de medida de energia electrica, diseno de planos y revision tecnica "
    "de instalaciones bajo normativa colombiana: RETIE 2024 y CREG 038/2014.\n"
    "No eres un transcriptor. ANALIZA, INTERPRETA y CORRIGE antes de responder. "
    "Si ves algo tecnicamente incorrecto en la imagen, señalalo aunque el usuario "
    "no lo haya preguntado.\n\n"
    "Analiza la imagen del bloque de pruebas / bornera de medida.\n\n"
    "TIPO DE MEDIDA: {tipo}\n"
    "NORMA APLICABLE: {norma}\n\n"
    "EVALÚA PUNTO POR PUNTO:\n\n"
    "1. CÓDIGO DE COLORES (RETIE 2024, Título 5):\n"
    "   R→rojo  |  S→azul  |  T→amarillo  |  N→blanco/gris  |  Tierra→verde\n\n"
    "2. POLARIDAD DE CORRIENTE:\n"
    "   TCs correctamente orientados (P1 entrada, P2 salida).\n"
    "   Detecta inversión de polaridad si es visible.\n\n"
    "3. PUENTES DE TENSIÓN:\n"
    "   ¿Están instalados los puentes de tensión donde corresponde?\n\n"
    "4. CORTOCIRCUITADORES DE CORRIENTE:\n"
    "   ¿Posición correcta para medida normal (abiertos)?\n\n"
    "5. TERMINALES / BORNERA:\n"
    "   Secuencia correcta según norma {norma}.\n"
    "   Terminales sueltos, conductores sin terminal, cruces.\n\n"
    "6. ESTADO FÍSICO:\n"
    "   Aislamiento dañado, corrosión, contaminación, tornillos flojos.\n\n"
    "RESPONDE EXACTAMENTE con este formato:\n\n"
    "🔍 DIAGNÓSTICO DE CONEXIONES\n"
    "─────────────────────────\n"
    "Estado: [✅ CORRECTO | ⚠️ CON OBSERVACIONES | ❌ INCORRECTO]\n\n"
    "HALLAZGOS:\n"
    "- [✅/⚠️/❌] descripción breve y específica de cada hallazgo\n\n"
    "CORRECCIONES:\n"
    "- acción específica numerada (o 'Ninguna' si todo está bien)\n\n"
    "NORMATIVA:\n"
    "- artículo o sección exacta que aplica\n\n"
    "ADVERTENCIA DE SEGURIDAD:\n"
    "- riesgo específico si aplica (o 'Ninguna')\n\n"
    "Si la imagen no muestra un sistema de medida eléctrica o no tiene suficiente "
    "resolución para evaluar, indícalo claramente."
)

# ── Calculadora de Burden ─────────────────────────────────────────────────────
# VA estimado por clase de exactitud del medidor (IEC 62053 / valores típicos campo)
_METER_VA = {"0.2S": 2.0, "0.5S": 2.0, "1": 3.0, "2": 3.0}

# Teclados reutilizables
_KB_BD_NOMINAL = InlineKeyboardMarkup([
    [InlineKeyboardButton("5 VA",  callback_data="bd_nominal:5"),
     InlineKeyboardButton("10 VA", callback_data="bd_nominal:10"),
     InlineKeyboardButton("15 VA", callback_data="bd_nominal:15")],
    [InlineKeyboardButton("25 VA", callback_data="bd_nominal:25"),
     InlineKeyboardButton("30 VA", callback_data="bd_nominal:30")],
])
_KB_BD_CABLE_LONG = InlineKeyboardMarkup([
    [InlineKeyboardButton("10 m",  callback_data="bd_cl_long:10"),
     InlineKeyboardButton("20 m",  callback_data="bd_cl_long:20"),
     InlineKeyboardButton("30 m",  callback_data="bd_cl_long:30")],
    [InlineKeyboardButton("50 m",  callback_data="bd_cl_long:50"),
     InlineKeyboardButton("100 m", callback_data="bd_cl_long:100")],
])
_KB_BD_CABLE_SEC = InlineKeyboardMarkup([
    [InlineKeyboardButton("2.5 mm²", callback_data="bd_cl_sec:2.5"),
     InlineKeyboardButton("4 mm²",   callback_data="bd_cl_sec:4"),
     InlineKeyboardButton("6 mm²",   callback_data="bd_cl_sec:6")],
    [InlineKeyboardButton("10 mm²",  callback_data="bd_cl_sec:10"),
     InlineKeyboardButton("16 mm²",  callback_data="bd_cl_sec:16")],
])
_KB_BD_MED_CLASE = InlineKeyboardMarkup([
    [InlineKeyboardButton("Clase 0.2S", callback_data="bd_med_clase:0.2S"),
     InlineKeyboardButton("Clase 0.5S", callback_data="bd_med_clase:0.5S")],
    [InlineKeyboardButton("Clase 1",    callback_data="bd_med_clase:1"),
     InlineKeyboardButton("Clase 2",    callback_data="bd_med_clase:2")],
])
_KB_BD_RELE = InlineKeyboardMarkup([
    [InlineKeyboardButton("— Sin relé", callback_data="bd_rele_va:0"),
     InlineKeyboardButton("1 VA",        callback_data="bd_rele_va:1")],
    [InlineKeyboardButton("2 VA",        callback_data="bd_rele_va:2"),
     InlineKeyboardButton("5 VA",        callback_data="bd_rele_va:5")],
])

def _bd_txt_nominal(tipo_lbl, clase):
    return (
        f"🧮 Burden {tipo_lbl}  ·  Clase {clase}\n"
        "─────────────────────────\n\n"
        f"¿Burden nominal del {tipo_lbl}? (VA)\n\n"
        "  Está en la placa del equipo.\n"
        "  Pulsa o escribe el valor:"
    )
def _bd_txt_cable_long():
    return (
        "🧮 Burden TC  ·  Cable\n"
        "─────────────────────────\n\n"
        "¿Longitud total del cable de corriente? (m)\n\n"
        "  Mide ida + vuelta: TC → medidor.\n"
        "  Pulsa o escribe:"
    )
def _bd_txt_cable_sec():
    return (
        "🧮 Burden TC  ·  Cable\n"
        "─────────────────────────\n\n"
        "¿Sección del cable de corriente? (mm²)\n\n"
        "  Pulsa o escribe:"
    )
def _bd_txt_med_clase():
    return (
        "🧮 Burden  ·  Medidor\n"
        "─────────────────────────\n\n"
        "¿Clase de exactitud del medidor?\n\n"
        "  El burden VA se estima automáticamente:\n"
        "  0.2S / 0.5S → 2 VA  ·  Clase 1 / 2 → 3 VA"
    )
def _bd_txt_rele():
    return (
        "🧮 Burden  ·  Relé\n"
        "─────────────────────────\n\n"
        "¿Hay relé de medida conectado al TC/TP?\n\n"
        "  Pulsa o escribe el valor en VA:"
    )

def _calcular_burden(bd):
    RHO   = 0.0172
    I_n   = float(bd.get("i_n", 5))
    S_nom = float(bd["nominal"])
    S_med = float(bd.get("s_med", 0))
    S_rel = float(bd.get("s_rele", 0))
    tipo  = bd.get("tipo", "tc")
    clase_med = bd.get("med_clase", "")

    if tipo == "tc":
        L = float(bd.get("cable_long", 0))
        A = float(bd.get("cable_sec", 1))
        R = 2 * L * RHO / A
        S_cable = I_n ** 2 * R
    else:
        S_cable = 0.0

    S_total = S_cable + S_med + S_rel
    cumple  = S_total <= S_nom
    margen  = S_nom - S_total
    pct     = margen / S_nom * 100

    lines = ["🧮 RESULTADO DE BURDEN", "─────────────────────────", ""]
    if tipo == "tc":
        lines.append(f"  Cable ({bd.get('cable_long','?')} m · {bd.get('cable_sec','?')} mm²)   {S_cable:.2f} VA")
    med_lbl = f"Medidor  clase {clase_med}" if clase_med else "Medidor"
    lines.append(f"  {med_lbl:<30}  {S_med:.2f} VA*")
    if S_rel:
        lines.append(f"  Relé                              {S_rel:.2f} VA")
    lines += [
        "  ─────────────────────────",
        f"  Total cargado                    {S_total:.2f} VA",
        f"  Nominal {tipo.upper()}                      {S_nom:.2f} VA",
        "",
        f"  {'✅ CUMPLE' if cumple else '❌ NO CUMPLE'}",
    ]
    if cumple:
        lines.append(f"  Margen libre   {margen:.2f} VA  ({pct:.0f}%)")
        if pct < 25:
            lines += ["", f"  ⚠️ Margen < 25% — considera {tipo.upper()} de mayor burden."]
    else:
        lines += ["", "RECOMENDACIONES:"]
        S_cable_max = S_nom - S_med - S_rel
        if S_cable_max > 0 and tipo == "tc":
            L = float(bd.get("cable_long", 0))
            A = float(bd.get("cable_sec", 1))
            A_min = I_n**2 * 2 * L * RHO / S_cable_max
            L_max = S_cable_max * A / (I_n**2 * 2 * RHO)
            lines.append(f"  1. Sección de cable ≥ {A_min:.1f} mm²")
            lines.append(f"  2. Longitud de cable ≤ {L_max:.1f} m")
        extra = max(S_total - S_nom, 0)
        lines.append(f"  3. Usar {tipo.upper()} con burden nominal ≥ {S_nom + extra + 2:.0f} VA")

    lines += [
        "",
        "* VA medidor estimado por clase de exactitud.",
        "  Verificar en placa o ficha técnica.",
        "─────────────────────────",
        "CREG 038/2014  ·  IEC 61869-2",
    ]
    return "\n".join(lines)

async def _analizar_foto_cx(image_bytes: bytes, tipo: str, norma: str) -> str:
    if not _genai_client:
        return "⚠️ Servicio de análisis de imágenes no disponible."
    prompt = PROMPT_VALIDACION_CX.format(tipo=tipo, norma=norma)
    try:
        response = await _genai_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt,
            ],
        )
        texto = (response.text or "").strip()
        texto = texto.replace("**", "").replace("__", "")
        return texto or "⚠️ El modelo no generó diagnóstico. Intenta con una foto más nítida."
    except Exception as e:
        log.error(f"Error Gemini Vision: {e}")
        return "⚠️ No pude analizar la imagen. Asegúrate de que la foto sea clara y bien iluminada."

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
            FileSearch = getattr(types, "FileSearch", None)
            if FileSearch is not None:
                try:
                    tools.append(types.Tool(
                        file_search=FileSearch(file_search_store_names=[RETIE_STORE_NAME])
                    ))
                except Exception as _te:
                    log.warning(f"FileSearch tool error: {_te}")
            else:
                log.warning("types.FileSearch no disponible en esta versión de google-genai; continuando sin RAG indexado.")

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

        if not tools:
            respuesta += (
                "\n\n⚠️ [Respuesta basada en conocimiento memorizados — verificar con norma oficial.]"
            )

        await _enviar_largo(update, respuesta)

    except Exception as e:
        log.error(f"Error Gemini [{type(e).__name__}]: {e}")
        msg = str(e)
        if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
            await update.message.reply_text(
                "⏳ El servicio normativo está saturado. Intenta de nuevo en unos segundos."
            )
        elif "401" in msg or "API_KEY" in msg.upper() or "invalid api key" in msg.lower() or "api key" in msg.lower():
            await update.message.reply_text(
                "⚠️ Clave API de Gemini inválida o no configurada.\n"
                "Verifica la variable GEMINI_API_KEY en Render."
            )
        elif "429" in msg or "quota" in msg.lower() or "RESOURCE_EXHAUSTED" in msg:
            await update.message.reply_text(
                "⏳ Cuota de Gemini agotada. Intenta en unos minutos."
            )
        elif "404" in msg or "not found" in msg.lower():
            await update.message.reply_text(
                "⚠️ Modelo Gemini no disponible. Revisa GEMINI_MODEL en el código."
            )
        else:
            await update.message.reply_text(
                f"⚠️ Error al consultar normativa: {type(e).__name__}\n"
                "Para diagramas usa /menu."
            )


async def _dialogo_diagrama(update: Update, ctx: ContextTypes.DEFAULT_TYPE, texto_usuario: str):
    """Conversacion guiada por Gemini para recopilar specs del diagrama."""
    historial: list = ctx.user_data.setdefault("historial_diagrama", [])
    historial.append({"role": "user", "parts": [{"text": texto_usuario}]})

    await update.message.reply_chat_action("typing")
    try:
        response = await _genai_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=[{"role": m["role"], "parts": m["parts"]} for m in historial],
            config=types.GenerateContentConfig(system_instruction=PROMPT_DIAGRAMA),
        )
        respuesta = (response.text or "").strip()
    except Exception as e:
        log.error(f"Error dialogo_diagrama: {e}")
        await update.message.reply_text(
            "⚠️ Error temporal con el servicio IA.\n"
            "Intenta de nuevo o usa /menu para el flujo guiado."
        )
        return

    respuesta_clean = respuesta.replace("**", "").replace("__", "")

    if "DIAGRAMA_LISTO" in respuesta:
        json_m = re.search(r"```json\s*(\{.*?\})\s*```", respuesta, re.DOTALL)
        if json_m:
            try:
                ia_cfg = json.loads(json_m.group(1))
                cfg = dict(DEFAULT)
                for k, v in ia_cfg.items():
                    if v is not None and v != "":
                        cfg[k] = v
                if cfg.get("trafo_tipo") and not cfg.get("trafo_uso"):
                    cfg["trafo_uso"] = cfg["trafo_tipo"]
                ctx.user_data["modo_diagrama_ia"] = False
                ctx.user_data["historial_diagrama"] = []
                await update.message.reply_text("Generando diagrama…")
                await _enviar_foto(update.message, cfg)
                return
            except (json.JSONDecodeError, KeyError) as e:
                log.error(f"JSON malformado de Gemini diagrama: {e}")
        ctx.user_data["modo_diagrama_ia"] = False
        ctx.user_data["historial_diagrama"] = []
        await update.message.reply_text(
            "⚠️ No pude procesar la especificacion. Usa /menu para el flujo guiado."
        )
        return

    historial.append({"role": "model", "parts": [{"text": respuesta}]})
    if len(historial) == 2:
        respuesta_clean = respuesta_clean + "\n\n_Escribe /cancelar para salir en cualquier momento._"
    await update.message.reply_text(respuesta_clean)


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
        "diagrama","unifilar","conexiones","dibuja","dibujame","grafica",
        "graficame","genera el diagrama","muéstrame el diagrama",
        "muestrame el diagrama","esquema de conexion","esquema de conexión",
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
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    estado, nombre, es_nuevo = await _check_user(user, force=True)

    if estado == "Inactivo":
        await update.message.reply_text(
            f"⚠️ Hola, {nombre}.\n\n"
            "Tu suscripción se encuentra suspendida.\n"
            "Contacta al administrador para reactivarla."
        )
        return

    if estado == "Pendiente":
        if es_nuevo and ADMIN_TG_ID:
            try:
                fecha = time.strftime("%Y-%m-%d %H:%M")
                await ctx.bot.send_message(
                    ADMIN_TG_ID,
                    f"🆕 Nuevo usuario registrado\n"
                    f"─────────────────────────\n"
                    f"  Nombre:    {nombre}\n"
                    f"  ID:        {user.id}\n"
                    f"  Username:  @{user.username or '—'}\n"
                    f"  Fecha:     {fecha}\n\n"
                    f"Activa o rechaza su acceso:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Activar",  callback_data=f"adm_ok:{user.id}"),
                        InlineKeyboardButton("❌ Rechazar", callback_data=f"adm_no:{user.id}"),
                    ]])
                )
            except Exception:
                pass
        await update.message.reply_text(
            f"👋 Hola, {nombre}!\n\n"
            "Tu registro está pendiente de activación.\n"
            "Recibirás acceso una vez que el administrador\n"
            "te habilite en el sistema.\n\n"
            "Escribe /start nuevamente cuando te confirmen."
        )
        return

    # Activo (o sin_sheets en modo degradado)
    await update.message.reply_text(
        f"⚡ Bienvenido, {nombre}!\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "¿En qué te ayudo hoy?\n\n"
        "  📐 /menu       Configurar un diagrama\n"
        "  💬 Escríbeme  Consulta normativa\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=REPLY_KEYBOARD
    )

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
    if not await _access_ok(update, ctx): return
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
    if not await _access_ok(update, ctx): return
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
                "  Con respaldo     principal + respaldo en mismo bloque"),
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def _kb_respaldo_msg(msg, cfg, n):
    kb = _kb([("Solo principal","no"),("✚  Con respaldo","si")], "respaldo")
    await msg.reply_text(
        _header(n, cfg,
                "¿Configuración de medidores?\n\n"
                "  Solo principal   un medidor\n"
                "  Con respaldo     principal + respaldo en mismo bloque"),
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ── cmd_menu ──────────────────────────────────────────────────────────────────
_MENU_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("📐  Diagrama",        callback_data="inicio:diagramas"),
     InlineKeyboardButton("📷  Validar cx",      callback_data="inicio:validar")],
    [InlineKeyboardButton("💬  Consulta",        callback_data="inicio:consultas"),
     InlineKeyboardButton("🧮  Burden TC/TP",   callback_data="inicio:burden")],
])
_MENU_TXT = (
    "⚡ BotElectric\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "¿Qué necesitas hoy?"
)

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _access_ok(update, ctx): return
    ctx.user_data.clear()
    ctx.user_data["cfg"] = dict(DEFAULT)
    ctx.user_data["paso_n"] = 1
    await update.message.reply_text(_MENU_TXT, reply_markup=_MENU_KB)

# ── on_button: máquina de estados completa ────────────────────────────────────
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _access_ok(update, ctx): return
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
        elif val == "validar":
            ctx.user_data["validando_foto"] = True
            ctx.user_data["val_tipo"] = "no especificado"
            ctx.user_data["val_norma"] = "no especificada"
            kb = _kb([
                ("⬇ Directa",     "directa"),
                ("⚡ Semidirecta", "semidirecta"),
                ("🔭 Indirecta",  "indirecta"),
            ], "val_tipo")
            await q.edit_message_text(
                "📷 Validación de conexiones\n"
                "─────────────────────────\n\n"
                "Voy a analizar la foto con IA y detectar errores.\n\n"
                "Primero dime: ¿tipo de medida?",
                reply_markup=InlineKeyboardMarkup(kb)
            )

        elif val == "burden":
            ctx.user_data["burden_data"] = {}
            kb = _kb([
                ("TC — corriente", "tc"),
                ("TP — tensión",   "tp"),
            ], "burden_tipo")
            await q.edit_message_text(
                "🧮 Calculadora de Burden\n"
                "─────────────────────────\n\n"
                "El burden es la carga conectada al secundario del TC o TP.\n"
                "Si excede el valor nominal, el equipo pierde exactitud.\n\n"
                "¿Qué equipo vas a calcular?",
                reply_markup=InlineKeyboardMarkup(kb)
            )

        else:
            if _genai_client:
                ctx.user_data["modo_diagrama_ia"] = True
                ctx.user_data["historial_diagrama"] = []
                await q.edit_message_text(
                    "📐 Diseño de Diagrama\n"
                    "──────────────────────────────\n\n"
                    "Describe tu instalacion y yo hago las preguntas necesarias.\n\n"
                    "Ejemplos:\n"
                    "  medida semidirecta trifasica, trafo 225 kVA\n"
                    "  conexiones directa monofasica norma CENS\n"
                    "  indirecta industrial 13.2 kV con unifilar\n\n"
                    "Escribe tu descripcion:"
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
                _adv()
                ctx.user_data["esperando_n_trafos"] = True
                await q.edit_message_text(
                    _header(n, cfg, "¿Cuántos transformadores de potencia?\n\n"
                                    "  Escribe el número  ej: 1  2  3  ...")
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
                    ("Simétrica — neutro CENTRO",  "simetrica"),
                    ("Asimétrica — neutro FINAL",  "asimetrica"),
                ], "conexion")
                await q.edit_message_text(
                    _header(n, cfg,
                            "¿Patrón de la bornera del medidor?\n\n"
                            "  Simétrica   [F|N|N|F] — neutro en el CENTRO\n"
                            "  Asimétrica  [F|F|N|N] — neutro al FINAL"),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            elif tipo == "indirecta":
                if cfg.get("salida") == "conexiones":
                    # Solo diagrama de conexiones — ir directo a RTC
                    ctx.user_data["esperando_rel_tc"] = True
                    await q.edit_message_text(
                        _header(n, cfg, "¿Relación de los TCs?\n\n"
                                        "  Formato primario/secundario  ej: 200/5")
                    )
                else:
                    cfg["instalacion"] = "trafo"
                    _adv()
                    kb = _kb([("1  (un trafo)","1"),("2  (banco dos)","2"),("3  (banco tres)","3"),("4  (banco cuatro)","4")], "n_trafos")
                    await q.edit_message_text(
                        _header(n, cfg, "¿Cuántos transformadores de potencia?\n\n"
                                        "  1  — un transformador trifásico\n"
                                        "  2  — banco de 2 monofásicos\n"
                                        "  3  — banco de 3 monofásicos"),
                        reply_markup=InlineKeyboardMarkup(kb)
                    )
            else:  # semidirecta
                if cfg.get("salida") == "conexiones":
                    # Solo diagrama de conexiones — ir directo a RTC
                    ctx.user_data["esperando_rel_tc"] = True
                    await q.edit_message_text(
                        _header(n, cfg, "¿Relación de los TCs?\n\n"
                                        "  Formato primario/secundario  ej: 200/5")
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
        if cfg.get("salida") == "conexiones":
            ctx.user_data["esperando_rel_tc"] = True
            await q.edit_message_text(
                _header(n, cfg, "¿Relación de los TCs?\n\n"
                                "  Formato primario/secundario  ej: 200/5")
            )
        else:
            cfg["instalacion"] = "trafo"
            _adv()
            kb = _kb([("1  (un trafo)","1"),("2  (banco dos)","2"),("3  (banco tres)","3"),("4  (banco cuatro)","4")], "n_trafos")
            await q.edit_message_text(
                _header(n, cfg, "¿Cuántos transformadores de potencia?\n\n"
                                "  1  — un transformador trifásico\n"
                                "  2  — banco de 2 monofásicos\n"
                                "  3  — banco de 3 monofásicos"),
                reply_markup=InlineKeyboardMarkup(kb)
            )

    # ── Conexión del medidor (directa) ────────────────────────────────────────
    elif campo == "conexion":
        cfg["conexion"] = val
        _adv()
        if cfg.get("salida") == "conexiones":
            # Solo diagrama de conexiones — no necesita instalacion/trafo
            await _kb_norma_q(q, cfg, n)
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
        ctx.user_data["esperando_n_trafos"] = True
        await q.edit_message_text(
            _header(n, cfg, "¿Cuántos transformadores de potencia?\n\n"
                            "  Escribe el número  ej: 1  2  3  ...")
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

    # ── Validación de conexiones — tipo ──────────────────────────────────────
    elif campo == "val_tipo":
        ctx.user_data["val_tipo"] = val
        kb = _kb([("CENS","CENS"),("RA8","RA8")], "val_norma")
        await q.edit_message_text(
            "📷 Validación de conexiones\n"
            "─────────────────────────\n\n"
            f"Tipo: {val.capitalize()}\n\n"
            "¿Norma de la instalación?",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif campo == "val_norma":
        ctx.user_data["val_norma"] = val
        tipo = ctx.user_data.get("val_tipo", "no especificado")
        await q.edit_message_text(
            "📷 Validación de conexiones\n"
            "─────────────────────────\n\n"
            f"Tipo: {tipo.capitalize()}  ·  Norma: {val}\n\n"
            "✅ Listo. Ahora sube la foto del bloque de pruebas.\n\n"
            "  Consejos para mejor análisis:\n"
            "  - Foto nítida y bien iluminada\n"
            "  - Captura todo el bloque de pruebas\n"
            "  - Incluye los conductores y terminales"
        )

    # ── Burden — tipo TC/TP ───────────────────────────────────────────────────
    elif campo == "burden_tipo":
        ctx.user_data["burden_data"]["tipo"] = val
        tipo_lbl = "TC — corriente" if val == "tc" else "TP — tensión"
        kb = _kb([("0.2S","0.2S"),("0.5S","0.5S"),("Clase 1","1"),("Clase 2","2")], "burden_clase")
        await q.edit_message_text(
            f"🧮 Burden  ·  {tipo_lbl}\n"
            "─────────────────────────\n\n"
            "¿Clase de exactitud del equipo?\n\n"
            "  0.2S / 0.5S  medida de energía\n"
            "  Clase 1 / 2  protección o uso general",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif campo == "burden_clase":
        bd = ctx.user_data.setdefault("burden_data", {})
        bd["clase"] = val
        tipo_lbl = "TC" if bd.get("tipo") == "tc" else "TP"
        ctx.user_data["burden_paso"] = "nominal"
        await q.edit_message_text(
            _bd_txt_nominal(tipo_lbl, val),
            reply_markup=_KB_BD_NOMINAL
        )

    elif campo == "bd_nominal":
        bd = ctx.user_data.setdefault("burden_data", {})
        bd["nominal"] = val
        if bd.get("tipo") == "tc":
            ctx.user_data["burden_paso"] = "cable_long"
            await q.edit_message_text(_bd_txt_cable_long(), reply_markup=_KB_BD_CABLE_LONG)
        else:
            ctx.user_data["burden_paso"] = None
            await q.edit_message_text(_bd_txt_med_clase(), reply_markup=_KB_BD_MED_CLASE)

    elif campo == "bd_cl_long":
        bd = ctx.user_data.setdefault("burden_data", {})
        bd["cable_long"] = val
        ctx.user_data["burden_paso"] = "cable_sec"
        await q.edit_message_text(_bd_txt_cable_sec(), reply_markup=_KB_BD_CABLE_SEC)

    elif campo == "bd_cl_sec":
        bd = ctx.user_data.setdefault("burden_data", {})
        bd["cable_sec"] = val
        ctx.user_data["burden_paso"] = None
        await q.edit_message_text(_bd_txt_med_clase(), reply_markup=_KB_BD_MED_CLASE)

    elif campo == "bd_med_clase":
        bd = ctx.user_data.setdefault("burden_data", {})
        bd["med_clase"] = val
        bd["s_med"] = str(_METER_VA.get(val, 2.0))
        ctx.user_data["burden_paso"] = "rele"
        await q.edit_message_text(_bd_txt_rele(), reply_markup=_KB_BD_RELE)

    elif campo == "bd_rele_va":
        bd = ctx.user_data.setdefault("burden_data", {})
        bd["s_rele"] = val   # "0" = sin relé
        ctx.user_data["burden_paso"] = None
        await q.edit_message_text(_calcular_burden(bd))

    # ── Admin — activar / desactivar usuarios ────────────────────────────────
    elif campo in ("adm_ok", "adm_no"):
        if not ADMIN_TG_ID or update.effective_user.id != ADMIN_TG_ID:
            await q.answer("⛔ Sin permisos de administrador.", show_alert=True)
            return
        uid          = val
        nuevo_estado = "Activo" if campo == "adm_ok" else "Inactivo"
        loop = asyncio.get_event_loop()
        ok, nombre = await loop.run_in_executor(
            None, lambda: _gs_set_estado(uid, nuevo_estado)
        )
        if not ok:
            await q.answer("⚠️ Usuario no encontrado en el registro.", show_alert=True)
            return
        icono = "✅" if nuevo_estado == "Activo" else "🔴"
        try:
            old_txt = q.message.text or ""
            await q.edit_message_text(old_txt + f"\n\n{icono} {nombre}  →  {nuevo_estado}")
        except Exception:
            await q.answer(f"{icono} {nombre} → {nuevo_estado}", show_alert=True)
        try:
            if nuevo_estado == "Activo":
                msg_u = (
                    f"⚡ ¡Tu acceso fue activado, {nombre}!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "Ya puedes usar BotElectric.\n"
                    "Escribe /start para comenzar."
                )
            else:
                msg_u = (
                    f"⚠️ Hola, {nombre}.\n\n"
                    "Tu acceso al bot ha sido suspendido.\n"
                    "Contacta al administrador si crees que es un error."
                )
            await ctx.bot.send_message(int(uid), msg_u)
        except Exception as e:
            log.warning(f"No se pudo notificar al usuario {uid}: {e}")

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
            await q.edit_message_text(_MENU_TXT, reply_markup=_MENU_KB)

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
    if not await _access_ok(update, ctx): return
    cfg = ctx.user_data.get("cfg", dict(DEFAULT))
    txt = update.message.text.strip()
    n   = ctx.user_data.get("paso_n", 1)

    # ── Modo diagrama IA ──────────────────────────────────────────────────────
    if ctx.user_data.get("modo_diagrama_ia"):
        await _dialogo_diagrama(update, ctx, txt)
        return

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

    # ── Número de transformadores (texto libre) ───────────────────────────────
    if ctx.user_data.get("esperando_n_trafos"):
        val_str, err = _validar_numero(txt, "número de transformadores")
        if err:
            await update.message.reply_text(f"⚠️ {err}\n\nEscribe solo el número  ej: 1  2  3")
            return
        ctx.user_data["esperando_n_trafos"] = False
        n_tr = max(1, int(float(val_str)))
        cfg["n_trafos"] = n_tr
        ctx.user_data["cfg"] = cfg
        n += 1; ctx.user_data["paso_n"] = n
        if n_tr > 1:
            ctx.user_data["kva_trafo_idx"] = 0
            ctx.user_data["kva_trafo_list"] = []
            await update.message.reply_text(
                _header(n, cfg, f"¿Capacidad del transformador 1 de {n_tr}? (kVA)\n\n"
                                "  Escribe solo el número  ej: 167 o 500")
            )
        else:
            ctx.user_data["esperando_kva"] = True
            await update.message.reply_text(
                _header(n, cfg, "¿Capacidad del transformador? (kVA)\n\n"
                                "  Escribe solo el número  ej: 75 o 150")
            )
        return

    # ── kVA banco de trafos (uno por uno) ────────────────────────────────────
    if ctx.user_data.get("kva_trafo_idx") is not None:
        val_str, err = _validar_numero(txt, "kVA del transformador")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return
        idx = ctx.user_data["kva_trafo_idx"]
        lst = ctx.user_data.get("kva_trafo_list", [])
        lst.append(val_str)
        n_tr = cfg.get("n_trafos", 1)

        if len(lst) < n_tr:
            # Más trafos por configurar
            ctx.user_data["kva_trafo_idx"] = idx + 1
            ctx.user_data["kva_trafo_list"] = lst
            await update.message.reply_text(
                _header(n, cfg, f"¿Capacidad del transformador {idx+2} de {n_tr}? (kVA)\n\n"
                                "  Escribe solo el número  ej: 167 o 500")
            )
            return

        # Todos recolectados — guardar y continuar el flujo
        ctx.user_data.pop("kva_trafo_idx")
        ctx.user_data.pop("kva_trafo_list", None)
        cfg["trafo_kva_list"] = lst
        cfg["trafo_kva"] = lst[0] if len(set(lst)) == 1 else " + ".join(lst)
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
        elif cfg.get("salida") == "conexiones":
            # Solo conexiones — sin calibre de conductor
            await _kb_norma_msg(update.message, cfg, n)
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
        if cfg.get("salida") == "conexiones":
            # Solo conexiones — sin protección ni calibre
            await _kb_norma_msg(update.message, cfg, n)
        else:
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

    # ── Calculadora de Burden — entrada numérica por teclado ─────────────────
    burden_paso = ctx.user_data.get("burden_paso")
    if burden_paso in ("nominal", "cable_long", "cable_sec", "rele"):
        bd = ctx.user_data.setdefault("burden_data", {})
        val_str, err = _validar_numero(txt, "valor")
        if err:
            await update.message.reply_text(f"⚠️ {err}")
            return

        if burden_paso == "nominal":
            bd["nominal"] = val_str
            if bd.get("tipo") == "tc":
                ctx.user_data["burden_paso"] = "cable_long"
                await update.message.reply_text(_bd_txt_cable_long(), reply_markup=_KB_BD_CABLE_LONG)
            else:
                ctx.user_data["burden_paso"] = None
                await update.message.reply_text(_bd_txt_med_clase(), reply_markup=_KB_BD_MED_CLASE)

        elif burden_paso == "cable_long":
            bd["cable_long"] = val_str
            ctx.user_data["burden_paso"] = "cable_sec"
            await update.message.reply_text(_bd_txt_cable_sec(), reply_markup=_KB_BD_CABLE_SEC)

        elif burden_paso == "cable_sec":
            bd["cable_sec"] = val_str
            ctx.user_data["burden_paso"] = None
            await update.message.reply_text(_bd_txt_med_clase(), reply_markup=_KB_BD_MED_CLASE)

        elif burden_paso == "rele":
            bd["s_rele"] = val_str
            ctx.user_data["burden_paso"] = None
            await update.message.reply_text(_calcular_burden(bd))

        return

    # ── Texto libre (consulta o diagrama rápido) ──────────────────────────────
    await _procesar_texto(update, update.message.text)

# ── Handler de fotos (validación de conexiones) ───────────────────────────────
async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _access_ok(update, ctx): return
    if not ctx.user_data.get("validando_foto"):
        await update.message.reply_text(
            "📷 Para analizar conexiones usa:\n"
            "/menu → 📷 Validar cx"
        )
        return

    ctx.user_data["validando_foto"] = False
    tipo  = ctx.user_data.pop("val_tipo",  "no especificado")
    norma = ctx.user_data.pop("val_norma", "no especificada")

    await update.message.reply_chat_action("typing")
    await update.message.reply_text(
        "🔍 Analizando conexiones…\n"
        "Esto puede tomar unos segundos."
    )

    # Descargar la foto en mayor resolución disponible
    photo = update.message.photo[-1]
    tg_file = await ctx.bot.get_file(photo.file_id)
    import io
    bio = io.BytesIO()
    await tg_file.download_to_memory(bio)
    image_bytes = bio.getvalue()

    resultado = await _analizar_foto_cx(image_bytes, tipo, norma)
    await update.message.reply_text(resultado)
    await update.message.reply_text(
        "¿Quieres generar el diagrama correcto? → /menu"
    )

# ── /admin — Panel de gestión de usuarios (solo admin) ───────────────────────
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not ADMIN_TG_ID or user.id != ADMIN_TG_ID:
        return  # ignorar silenciosamente
    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(None, _gs_get_all_users)
    if not rows:
        await update.message.reply_text(
            "👤 Panel de administración\n"
            "─────────────────────────\n\n"
            "No hay usuarios registrados aún."
        )
        return
    lines   = ["👤 Panel de administración", "─────────────────────────", ""]
    kb_rows = []
    for row in rows[:20]:
        uid    = str(row.get("Telegram_ID", ""))
        nombre = str(row.get("Nombre",      "—"))
        uname  = str(row.get("Username",    "—"))
        estado = str(row.get("Estado",      "Pendiente"))
        fecha  = str(row.get("Fecha_Registro", "—"))
        icono  = "✅" if estado == "Activo" else ("⏳" if estado == "Pendiente" else "🔴")
        lines.append(f"{icono} {nombre}  {uname}")
        lines.append(f"   {estado}  ·  {fecha}")
        lines.append("")
        btns = []
        if estado != "Activo":
            btns.append(InlineKeyboardButton("✅ Activar",     callback_data=f"adm_ok:{uid}"))
        if estado != "Inactivo":
            btns.append(InlineKeyboardButton("🔴 Desactivar", callback_data=f"adm_no:{uid}"))
        if btns:
            kb_rows.append(btns)
    if len(rows) > 20:
        lines.append(f"⚠️ Mostrando 20 de {len(rows)} usuarios.")
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else None
    )

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
    app.add_handler(CommandHandler("admin",      cmd_admin))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
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
