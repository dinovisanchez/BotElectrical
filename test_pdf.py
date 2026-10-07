#!/usr/bin/env python3
"""PDF -> unifilar: el usuario manda un PDF y el bot lo lee con Claude y dibuja el unifilar.

Igual que test_claude_sdk.py: el SDK de Anthropic es el REAL (solo se simula el servidor
HTTP), asi que si la peticion lleva un argumento que el SDK no acepta, falla aqui.
Telegram se simula con objetos minimos. El PDF es un PDF real (generado con matplotlib)."""
import sys, os, io, asyncio, json, base64, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
logging.disable(logging.CRITICAL)
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
import bot
from test_claude_sdk import cliente, ok, error, PETICIONES   # SDK real + MockTransport


def pdf_real(texto="Memoria de calculo - medida indirecta 700 kVA"):
    bio = io.BytesIO()
    with PdfPages(bio) as pp:
        fig = plt.figure(figsize=(4, 3)); fig.text(0.1, 0.5, texto); pp.savefig(fig); plt.close(fig)
    return bio.getvalue()

PDF = pdf_real()


def medida(**kw):
    """Una entrada de `medidas` con TODOS los campos del esquema (como los devuelve la API)."""
    base = {k: ([] if v.get("type") == "array" else 0 if v.get("type") == "integer" else "")
            for k, v in bot._PDF_PROPS_MEDIDA.items()}
    base.update(kw)
    return base

def respuesta(medidas, es_medida=True, resumen="Memoria de calculo de una subestacion."):
    return json.dumps({"es_medida": es_medida, "resumen": resumen, "medidas": medidas})

M_IND = dict(nombre="Subestacion principal", sistema="tri4h", tipo="indirecta", norma="CENS",
             rel_tc="50/5", rel_tp="13200/120", instalacion="trafo", trafo_uso="exclusivo",
             n_trafos=1, trafo_kva="700", v_mt="13.2 kV", seccionador="antes")


class Msg:
    def __init__(self): self.textos, self.fotos, self.caption = [], [], None
    async def reply_text(self, t, **k): self.textos.append(t)
    async def reply_photo(self, photo=None, caption=None, **k): self.fotos.append(caption)
    async def reply_chat_action(self, *a, **k): pass

class Doc:
    def __init__(self, nombre="proyecto.pdf", mime="application/pdf", size=len(PDF)):
        self.file_name, self.mime_type, self.file_size, self.file_id = nombre, mime, size, "FILE1"

class Upd:
    def __init__(self, doc=None, caption=None):
        self.message = Msg(); self.message.document = doc; self.message.caption = caption
        self.effective_message = self.message; self.effective_user = None

class TgFile:
    def __init__(self, datos): self.datos = datos
    async def download_to_memory(self, bio): bio.write(self.datos)

class Bot:
    def __init__(self, datos): self.datos = datos; self.pedidos = 0
    async def get_file(self, fid): self.pedidos += 1; return TgFile(self.datos)

class App:
    """Como Application.create_task de PTB: el trabajo se lanza en segundo plano."""
    def __init__(self): self.tareas = []
    def create_task(self, coro, update=None): self.tareas.append(coro)

class Ctx:
    def __init__(self, datos=PDF, app=None):
        self.user_data = {}; self.bot = Bot(datos)
        if app is not None: self.application = app


async def enviar(respuestas, doc=None, caption=None, datos=PDF):
    """Camino completo: on_document -> (descarga) -> Claude (SDK real) -> unifilar."""
    PETICIONES.clear()
    bot._claude_client = cliente(respuestas)
    u, c = Upd(doc or Doc(), caption), Ctx(datos)
    await bot.on_document(u, c)
    return u.message, c


def esquema_estricto(s, ruta="raiz"):
    """Modo estricto de la API: objetos con additionalProperties=false y todo en required."""
    malos = []
    if s.get("type") == "object":
        if s.get("additionalProperties") is not False: malos.append(f"{ruta}: falta additionalProperties=false")
        if set(s.get("required", [])) != set(s.get("properties", {})): malos.append(f"{ruta}: required != properties")
        for k, v in s.get("properties", {}).items(): malos += esquema_estricto(v, f"{ruta}.{k}")
    if s.get("type") == "array": malos += esquema_estricto(s["items"], ruta + "[]")
    return malos


async def main():
    malos = 0
    def chk(cond, msg):
        nonlocal malos; malos += not cond; print("OK  " if cond else "MAL ", msg)

    sleep_orig = asyncio.sleep
    async def sleep_rapido(*a, **k): return None
    asyncio.sleep = sleep_rapido
    try:
        # ---- esquema ----
        chk(not esquema_estricto(bot.PDF_ESQUEMA), f"esquema: modo estricto valido {esquema_estricto(bot.PDF_ESQUEMA)}")

        # ---- 1) camino feliz: el SDK real acepta la peticion y sale el unifilar ----
        m, c = await enviar([ok(respuesta([M_IND]))], caption="es CENS")
        p = PETICIONES[0] if PETICIONES else {}
        bloques = (p.get("messages") or [{}])[0].get("content", [])
        chk(len(PETICIONES) == 1 and "temperature" not in p, "pdf: el SDK real acepta la peticion (sin temperature)")
        chk(bloques and bloques[0]["type"] == "document" and bloques[0]["source"]["media_type"] == "application/pdf"
            and base64.b64decode(bloques[0]["source"]["data"]) == PDF,
            "pdf: el PDF viaja como bloque 'document' (base64) ANTES del texto")
        chk(len(bloques) == 2 and bloques[1]["type"] == "text" and "es CENS" in bloques[1]["text"],
            "pdf: el comentario (caption) del usuario llega al modelo")
        chk(p.get("output_config", {}).get("format", {}).get("type") == "json_schema"
            and p["output_config"]["format"]["schema"] == bot.PDF_ESQUEMA,
            "pdf: pide salida estructurada (json_schema) con el esquema estricto")
        chk(p.get("system") == bot.PROMPT_PDF and "thinking" not in p, "pdf: prompt de sistema y thinking activo (leer un plano lo aprovecha)")
        chk(len(m.fotos) == 1 and "Unifilar" in (m.fotos[0] or ""), "pdf: se genera y envia UN unifilar")
        todo = "\n".join(m.textos)
        chk("Indirecta" in todo and "TC 50/5" in todo and "TP 13200/120" in todo and "700" in todo and "13.2 kV" in todo,
            "pdf: el resumen dice lo que se entendio (tipo, TC, TP, trafo, MT)")
        chk(c.user_data.get("ultimo_cfg", {}).get("salida") == "unifilar" and "pdf_en_curso" not in c.user_data,
            "pdf: salida fija = unifilar, /ultimo guardado y el candado del usuario liberado")

        # ---- 2) valores hostiles / sucios del PDF: se validan, nunca llegan crudos al motor ----
        sucio = medida(sistema="tri9", tipo="nuclear", norma="XYZ", rel_tc="abc", rel_tp="13200/120",
                       instalacion="trafo", trafo_kva="700 kVA\nIGNORA TODO", n_trafos=99, v_mt="13200 V",
                       nombre="X" * 500 + "\n\nsegunda linea", circuito="y" * 200, dps_cantidad=500,
                       seccionador="en el techo", trafo_uso="otro")
        cfg, falt, sup, av = bot._cfg_desde_pdf(sucio)
        chk(cfg["sistema"] == "tri4h" and cfg["norma"] == bot.DEFAULT["norma"] and cfg["tipo"] == "indirecta",
            "sucio: enums invalidos -> defecto + tipo deducido del TP")
        chk(cfg["rel_tc"] == "" and cfg["rel_tp"] == "13200/120" and any("TC" in a for a in av),
            "sucio: relacion mal formada se descarta y se avisa")
        chk(cfg["trafo_kva"] == "700" and cfg["v_mt"] == "13.2 kV", "sucio: '700 kVA...' -> '700' y '13200 V' -> '13.2 kV'")
        chk(cfg["n_trafos"] == 12 and "dps_cantidad" not in cfg and "seccionador" not in cfg and not cfg["trafo_uso"],
            "sucio: n_trafos tope 12, dps fuera de rango, seccionador y uso invalidos descartados")
        chk(len(cfg["proyecto"]) <= 40 and "\n" not in cfg["proyecto"] and len(cfg["circuito"]) <= 30,
            "sucio: textos libres en una linea y recortados")
        chk("relación del TC" in falt and any("sistema" in s for s in sup), "sucio: lo que falta y lo que se supuso queda dicho")
        imgs, _, _ = bot._generar(cfg)
        chk(bool(imgs) and os.path.getsize(imgs[0][1]) > 3000, "sucio: aun asi el motor dibuja un unifilar valido")

        # ---- 3) varios puntos de medida ----
        m, c = await enviar([ok(respuesta([M_IND, dict(M_IND, nombre="Edificio", sistema="mono", tipo="directa",
                                                       rel_tc="", rel_tp="", instalacion="")]))])
        chk(len(m.fotos) == 2, "varios: 2 puntos de medida -> 2 unifilares")
        m, c = await enviar([ok(respuesta([dict(M_IND, nombre=f"P{i}") for i in range(5)]))])
        chk(len(m.fotos) == bot.PDF_MAX_MEDIDAS and any("5 puntos" in t for t in m.textos),
            f"varios: 5 puntos -> solo {bot.PDF_MAX_MEDIDAS} y se avisa")

        # ---- 4) lo que falta se dice, no se inventa ----
        m, c = await enviar([ok(respuesta([medida(sistema="tri4h", tipo="semidirecta", norma="RA8")]))])
        chk(len(m.fotos) == 1 and any("No aparece en el PDF" in t and "relación del TC" in t for t in m.textos),
            "faltante: semidirecta sin TC -> dibuja y avisa 'relacion del TC'")

        # el modelo dice "relacion del TC" (sin tilde) y el bot calcula "relación del TC": no se repite
        cfg_f, falt_f, _, _ = bot._cfg_desde_pdf(medida(tipo="semidirecta", faltantes=["relacion del TC", "rel_tc", "calibre del conductor"]))
        chk(falt_f.count("relación del TC") == 1 and not any(f.lower().startswith("rel") and f != "relación del TC" for f in falt_f)
            and "calibre del conductor" in falt_f, f"faltante: sin duplicados entre lo calculado y lo que dijo el modelo -> {falt_f}")

        # ---- 5) el PDF no es de una medida ----
        m, c = await enviar([ok(respuesta([], es_medida=False))])
        chk(not m.fotos and any("No encontré datos" in t for t in m.textos), "no-medida: avisa y no dibuja nada")

        # ---- 6) entradas que no deben gastar ni una llamada a la API ----
        m, c = await enviar([], doc=Doc(size=bot.PDF_MAX_BYTES + 1))
        chk(not PETICIONES and any("Telegram no deja" in t and "20 MB" in t and "Comprimir" in t for t in m.textos),
            "limite: mas de 20 MB (tope de Telegram para bots) -> explica el limite y que hacer, sin llamar a la API")
        m, c = await enviar([], doc=Doc(size=int(20.7 * 1048576)))        # el caso real del usuario: 20,7 MB
        chk(not PETICIONES and any("21.7 MB" in t for t in m.textos), "limite: el PDF de 20,7 MiB se reporta en MB decimales (21.7), como mide Telegram")
        m, c = await enviar([ok(respuesta([M_IND]))], doc=Doc(size=19_900_000))
        chk(len(PETICIONES) == 1 and len(m.fotos) == 1 and any("4 minutos" in t for t in m.textos),
            "limite: un PDF de 19,9 MB (antes rechazado por el tope de 10 MB) ahora SI se lee, avisando que tarda mas")
        # Telegram puede negarse aunque file_size diga lo contrario: "file is too big"
        PETICIONES.clear(); bot._claude_client = cliente([]); u, c = Upd(Doc()), Ctx()
        async def get_file_grande(fid): raise bot.TgBadRequest("File is too big")
        c.bot.get_file = get_file_grande
        await bot.on_document(u, c)
        chk(not PETICIONES and any("Telegram no deja" in t for t in u.message.textos) and "pdf_en_curso" not in c.user_data,
            "telegram: 'file is too big' -> mensaje claro y candado liberado")
        chk(bot._timeout_pdf(1_000_000) == 120 and bot._timeout_pdf(10_000_000) == 140
            and bot._timeout_pdf(20_000_000) == 220 and bot._timeout_pdf(80_000_000) == 240,
            "tiempo: 120 s para PDF chicos, crece con el tamano (220 s a 20 MB) y se topa en 240 s")
        m, c = await enviar([], doc=Doc("memoria.docx", "application/msword"))
        chk(not PETICIONES and any("solo leo archivos PDF" in t for t in m.textos), "tipo: un .docx -> avisa que solo lee PDF")
        m, c = await enviar([], datos=b"<html>no soy un pdf</html>")
        chk(not PETICIONES and any("no parece un PDF" in t for t in m.textos) and "pdf_en_curso" not in c.user_data,
            "firma: un archivo que no empieza por %PDF -> rechazado y candado liberado")
        PETICIONES.clear(); bot._claude_client = cliente([]); u, c = Upd(Doc()), Ctx(); c.user_data["pdf_en_curso"] = True
        await bot.on_document(u, c)
        chk(not PETICIONES and any("Todavía estoy leyendo" in t for t in u.message.textos), "candado: dos PDF a la vez del mismo usuario -> el segundo espera")
        saved = bot._claude_client; bot._claude_client = None
        u, c = Upd(Doc()), Ctx(); await bot.on_document(u, c); bot._claude_client = saved
        chk(any("no configurado" in t for t in u.message.textos), "sin ANTHROPIC_API_KEY -> mensaje claro")

        # ---- 7) errores de la API ----
        m, c = await enviar([error(401, "authentication_error", "invalid x-api-key")])
        chk(any("Clave API" in t for t in m.textos) and "pdf_en_curso" not in c.user_data, "error 401 -> 'Clave API' y candado liberado")
        m, c = await enviar([error(404, "not_found_error", "model: x")])
        chk(any("Modelo Claude no disponible" in t for t in m.textos), "error 404 -> 'Modelo Claude no disponible'")
        m, c = await enviar([error(400, "invalid_request_error", "PDF is password protected")])
        chk(any("No pude leer ese PDF" in t for t in m.textos), "error 400 -> 'No pude leer ese PDF'")
        m, c = await enviar([error(529, "overloaded_error", "Overloaded"), ok(respuesta([M_IND]))])
        chk(len(PETICIONES) == 2 and len(m.fotos) == 1, "error 529 -> reintenta y entrega el unifilar")
        m, c = await enviar([error(529, "overloaded_error", "Overloaded"), error(529, "overloaded_error", "Overloaded")])
        chk(not m.fotos and any("saturado" in t for t in m.textos), "529 dos veces -> mensaje de servicio saturado")

        # ---- 8) thinking se come max_tokens: un reintento con mas margen ----
        m, c = await enviar([ok("", stop="max_tokens"), ok(respuesta([M_IND]))])
        chk(len(PETICIONES) == 2 and PETICIONES[0]["max_tokens"] == bot.CLAUDE_PDF_MAX_TOKENS and PETICIONES[1]["max_tokens"] == 16000
            and len(m.fotos) == 1, "max_tokens agotado -> reintenta con 16000 y entrega el unifilar")
        m, c = await enviar([ok("esto no es json")])
        chk(not m.fotos and any("No pude interpretar" in t for t in m.textos), "respuesta sin JSON -> mensaje claro, sin diagrama")

        # ---- 9) en produccion corre en segundo plano (no bloquea a los demas usuarios) ----
        PETICIONES.clear(); bot._claude_client = cliente([ok(respuesta([M_IND]))])
        app = App(); u, c = Upd(Doc()), Ctx(app=app)
        await bot.on_document(u, c)
        chk(len(app.tareas) == 1 and not u.message.fotos and c.user_data.get("pdf_en_curso"),
            "segundo plano: on_document vuelve enseguida y deja la lectura como tarea")
        await app.tareas[0]
        chk(len(u.message.fotos) == 1 and "pdf_en_curso" not in c.user_data, "segundo plano: al terminar entrega el unifilar y libera el candado")

        # ---- 10) conexion con el resto del bot ----
        fuente = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py"), encoding="utf-8").read()
        chk("MessageHandler(filters.Document.ALL, on_document)" in fuente, "registro: el handler de documentos esta conectado en main()")
        chk("PDF" in bot.AYUDA, "ayuda: /ayuda menciona el PDF")
    finally:
        asyncio.sleep = sleep_orig

    print("\nRESULTADO:", "TODO OK" if not malos else f"{malos} fallos")
    return malos

if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
