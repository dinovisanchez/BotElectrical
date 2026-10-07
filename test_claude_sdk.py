#!/usr/bin/env python3
"""Llamadas a Claude con el SDK REAL de Anthropic (no un cliente falso).

Motivo: con anthropic 1.x, messages.create() ya no acepta `temperature`; el bot lo
seguia pasando y TODO el dialogo de diagramas respondia "Error con el servicio IA
(TypeError)". Las pruebas anteriores usaban un objeto falso que aceptaba cualquier
argumento, por eso nadie lo vio. Aqui solo se simula el TRANSPORTE HTTP (el servidor):
el SDK real construye y valida la peticion, asi que un argumento no soportado falla aqui.

anthropic 1.x usa `httpx2` (no `httpx`); con 0.x se cae a `httpx`."""
import sys, os, asyncio, json, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
logging.disable(logging.CRITICAL)
import anthropic
try:
    import httpx2 as H
except ImportError:                      # anthropic 0.x
    import httpx as H
import bot

PETICIONES = []

def cliente(respuestas):
    """Cliente REAL; el servidor devuelve, en orden, cada elemento de `respuestas`:
    (status, json). Registra cada cuerpo de peticion en PETICIONES."""
    it = iter(respuestas)
    def handler(request):
        PETICIONES.append(json.loads(request.content))
        status, cuerpo = next(it)
        return H.Response(status, json=cuerpo)
    return anthropic.AsyncAnthropic(api_key="sk-test", max_retries=0,
                                    http_client=H.AsyncClient(transport=H.MockTransport(handler)))

def ok(texto, stop="end_turn", usage=None):
    return (200, {"id": "msg_1", "type": "message", "role": "assistant", "model": bot.CLAUDE_MODEL,
                  "content": [{"type": "text", "text": texto}], "stop_reason": stop, "stop_sequence": None,
                  "usage": usage or {"input_tokens": 10, "output_tokens": 10}})

class Registros(logging.Handler):
    """Captura lo que el bot escribe en su logger (el resto del test lo tiene silenciado)."""
    def __init__(self): super().__init__(); self.lineas = []
    def emit(self, r): self.lineas.append(r.getMessage())

def error(status, tipo, msg):
    return (status, {"type": "error", "error": {"type": tipo, "message": msg}})

class Msg:
    def __init__(self): self.textos, self.fotos = [], []
    async def reply_text(self, t, **k): self.textos.append(t)
    async def reply_photo(self, photo=None, caption=None, **k): self.fotos.append(caption)
    async def reply_chat_action(self, *a, **k): pass
class Upd:
    def __init__(self): self.message = Msg(); self.effective_message = self.message; self.effective_user = None
class Ctx:
    def __init__(self): self.user_data = {"modo_diagrama_ia": True}

JSON_LISTO = ("DIAGRAMA_LISTO\n```json\n"
              '{"sistema":"tri4h","tipo":"indirecta","salida":"unifilar","norma":"CENS","instalacion":"trafo",'
              '"trafo_uso":"exclusivo","n_trafos":1,"trafo_kva":"700","rel_tc":"50/5","rel_tp":"13200/120","v_mt":"13.2 kV"}\n```')

async def dialogo(respuestas, texto="medida indirecta trifasica 700 kva"):
    PETICIONES.clear()
    bot._claude_client = cliente(respuestas)
    u, c = Upd(), Ctx()
    await bot._dialogo_diagrama(u, c, texto)
    return u.message

async def main():
    malos = 0
    def chk(cond, msg):
        nonlocal malos; malos += not cond; print("OK  " if cond else "MAL ", msg)

    sleep_orig = asyncio.sleep
    async def sleep_rapido(*a, **k): return None
    asyncio.sleep = sleep_rapido            # el bot espera 4-8 s entre reintentos
    try:
        # 1) pregunta normal: el SDK real acepta la peticion y NO lleva temperature
        m = await dialogo([ok("¿Tipo de medida: directa, semidirecta o indirecta?")])
        chk(len(PETICIONES) == 1 and "temperature" not in PETICIONES[0], "dialogo: el SDK real acepta la peticion (sin temperature)")
        chk(m.textos and "Tipo de medida" in m.textos[0] and "Error con el servicio" not in m.textos[0], "dialogo: el usuario recibe la pregunta, no 'Error con el servicio IA'")
        chk(PETICIONES[0]["max_tokens"] == bot.CLAUDE_DIALOGO_MAX_TOKENS and PETICIONES[0]["model"] == bot.CLAUDE_MODEL, "dialogo: modelo y max_tokens esperados")

        # 1b) costo: el prompt va como bloque con cache_control y el thinking del dialogo esta apagado
        sysb = PETICIONES[0].get("system")
        chk(isinstance(sysb, list) and len(sysb) == 1 and sysb[0].get("text") == bot.PROMPT_DIAGRAMA
            and sysb[0].get("cache_control") == {"type": "ephemeral"},
            "costo: PROMPT_DIAGRAMA viaja como bloque con cache_control ephemeral (se cobra a precio de cache)")
        chk(PETICIONES[0].get("thinking") == {"type": "disabled"},
            "costo: el dialogo va con thinking desactivado (no se paga razonamiento oculto)")

        # 1c) el log de uso trae tokens, tokens de cache y costo estimado (US$)
        reg = Registros(); bot.log.addHandler(reg); prev = bot.log.level; bot.log.setLevel(logging.INFO)
        logging.disable(logging.NOTSET)
        try:
            await dialogo([ok("¿Tipo de medida?", usage={"input_tokens": 100, "output_tokens": 50,
                                                          "cache_read_input_tokens": 2700,
                                                          "cache_creation_input_tokens": 0})])
        finally:
            logging.disable(logging.CRITICAL); bot.log.removeHandler(reg); bot.log.setLevel(prev)
        linea = next((l for l in reg.lineas if l.startswith("claude[dialogo]")), "")
        # (100*2 + 50*10 + 2700*0.2) / 1e6 = US$0.00124
        chk("in=100" in linea and "cache_leido=2700" in linea and "out=50" in linea and "US$0.0012" in linea,
            f"costo: el log registra tokens, cache y costo estimado -> {linea!r}")
        try:
            r = bot._log_uso_claude("x", object())          # respuesta sin .usage: nunca debe lanzar
            chk(r is None, "costo: _log_uso_claude no lanza si la respuesta no trae usage")
        except Exception as e:
            chk(False, f"costo: _log_uso_claude lanzo {type(e).__name__}")

        # 2) flujo completo: DIAGRAMA_LISTO -> se GENERA y se ENVIA el unifilar
        m = await dialogo([ok(JSON_LISTO)])
        chk(len(m.fotos) == 1, "dialogo: DIAGRAMA_LISTO genera y envia el unifilar")
        chk(m.fotos and "Unifilar" in m.fotos[0], "dialogo: el caption corresponde al unifilar")

        # 3) limite de tokens agotado -> un reintento con el presupuesto completo
        m = await dialogo([ok("Para el unifilar necesito", stop="max_tokens"), ok(JSON_LISTO)])
        chk(len(PETICIONES) == 2 and PETICIONES[1]["max_tokens"] == bot.CLAUDE_MAX_TOKENS, "dialogo: max_tokens agotado -> reintenta con CLAUDE_MAX_TOKENS")
        chk(len(m.fotos) == 1, "dialogo: tras el reintento si se genera el diagrama")
        chk(PETICIONES[1].get("thinking") == {"type": "disabled"} and PETICIONES[1]["system"][0].get("cache_control"),
            "costo: el reintento por max_tokens conserva cache_control y thinking apagado")

        # 4) respuesta vacia (p.ej. todo el limite se fue en razonamiento) -> mensaje, no silencio
        m = await dialogo([ok("", stop="max_tokens"), ok("", stop="max_tokens")])
        chk(m.textos and "No pude generar una respuesta" in m.textos[-1], "dialogo: respuesta vacia -> mensaje claro (Telegram rechaza texto vacio)")

        # 5) servidor saturado (529) una vez -> reintenta y responde
        m = await dialogo([error(529, "overloaded_error", "Overloaded"), ok("¿Sistema monofasico, bifasico o trifasico?")])
        chk(len(PETICIONES) == 2 and any("Sistema" in t for t in m.textos), "dialogo: 529 -> reintenta y responde")

        # 6) clave invalida -> mensaje especifico
        m = await dialogo([error(401, "authentication_error", "invalid x-api-key")])
        chk(m.textos and "Clave API" in m.textos[0], "dialogo: 401 -> 'Clave API de Claude invalida'")

        # 7) modelo inexistente -> mensaje especifico
        m = await dialogo([error(404, "not_found_error", "model: x")])
        chk(m.textos and "Modelo Claude no disponible" in m.textos[0], "dialogo: 404 -> 'Modelo Claude no disponible'")

        # 8) analisis de foto: imagen en la peticion, sin temperature, devuelve el diagnostico
        PETICIONES.clear()
        bot._claude_client = cliente([ok("🔍 DIAGNÓSTICO DE CONEXIONES\nEstado: ✅ CORRECTO")])
        txt = await bot._analizar_foto_cx(b"\xff\xd8\xff\xe0fakejpeg", "indirecta", "CENS")
        bloques = PETICIONES[0]["messages"][0]["content"]
        chk("DIAGNÓSTICO" in txt and any(b["type"] == "image" for b in bloques) and "temperature" not in PETICIONES[0],
            "foto: el SDK real acepta la peticion con imagen (sin temperature) y devuelve el diagnostico")
        chk("thinking" not in PETICIONES[0], "foto: NO se desactiva el razonamiento (validar cableado si lo aprovecha)")
    finally:
        asyncio.sleep = sleep_orig

    print("\nRESULTADO:", "TODO OK" if not malos else f"{malos} fallos")
    return malos

if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
