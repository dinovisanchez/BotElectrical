# Bot de Telegram — Diagramas de sistemas de medida de energía

Bot que actúa como ingeniero de diseño eléctrico: recibe las especificaciones de una
medida y devuelve el **diagrama de conexiones** (Medidor ↔ Bloque de prueba ↔ TC/TP)
y/o el **diagrama unifilar técnico**.

## Casos soportados
- **Tipo:** directa · semidirecta · indirecta
- **Sistema:** monofásica · bifásica · trifásica 3 hilos (2 elementos) · trifásica 4 hilos (3 elementos)
- **Respaldo:** medidor principal + chequeo (1 bloque, 2 medidores)
- **Norma:** CENS (Cap. 6) · PA-NC-RA8 (nacional)
- **Salida:** diagrama de conexiones, unifilar, o ambos
- **Colores:** R rojo · S azul · T amarillo · N gris · tierra verde

## Archivos
- `diagram_engine.py` — motor de dibujo. `draw()` = conexiones, `draw_unifilar()` = unifilar.
- `parser.py` — interpreta texto libre y argumentos `clave=valor`.
- `bot.py` — bot de Telegram (comandos, texto libre y menú con botones).
- `test_e2e.py` — prueba local sin Telegram (texto → imagen).
- `requirements.txt` — dependencias.

## Instalación
```bash
pip install -r requirements.txt
```

## Crear el bot y obtener el token
1. En Telegram abre **@BotFather** → `/newbot` → sigue los pasos.
2. Copia el token (algo como `123456:ABC-DEF...`).

## Ejecutar
```bash
export BOT_TOKEN="TU_TOKEN_AQUI"     # Windows PowerShell: $env:BOT_TOKEN="..."
python bot.py
```

## Uso en el chat
**Texto libre:**
```
indirecta trifasica 3 elementos norma CENS 200/5 13200/120
unifilar semidirecta 300/5 13.2 kv
indirecta 3 elementos con respaldo 200/5 13200/120
unifilar y conexiones indirecta 200/5 13200/120
```
**Comando con parámetros:**
```
/diagrama tipo=indirecta sistema=tri4h norma=CENS rtc=200/5 rtp=13200/120 respaldo=si
```
**Menú con botones:** `/menu` (tipo → sistema → norma → respaldo → diagrama → relaciones)

**Otros comandos:** `/start`, `/help`, `/ayuda`

## Probar sin Telegram
```bash
python test_e2e.py        # genera PNGs de muestra de cada caso
python diagram_engine.py  # genera todas las muestras (conexiones + unifilar)
```

## Diagrama unifilar (simbología IEC/UNE 60617)
El unifilar usa símbolos estándar y trae un **plano de simbología** integrado.
Elementos: cortacircuitos fusible, interruptor automático, seccionador, pararrayos/DPS,
TC, TP, transformador de potencia, relé de protección (ANSI 27/49/50), puesta a tierra,
barra y carga. Se adapta al tipo de medida (indirecta = MT con TC/TP + trafo; semidirecta = BT).

Opciones por texto:
```
unifilar indirecta 13.2 kv 200/5 13200/120        # unifilar
unifilar y conexiones indirecta 200/5 13200/120   # ambos diagramas
unifilar indirecta con rele 50/51 200/5 13200/120 # incluye relé de protección
unifilar semidirecta sin pararrayos 300/5         # sin DPS
```

## Notas / pendientes para v2
- Los diagramas son esquemáticos y conformes al patrón de las normas (no copias CAD pixel a pixel).
- En 2 elementos (Aron) el motor dibuja un TP por fase; si la norma usa 2 TP línea-línea, se ajusta en `meter_terminals` / ruteo de TP.
- Posibles extensiones: diagrama fasorial, exportar a PDF, cajetín de proyecto, y numeración exacta de bornes B1–B26 (RA8).


### Caso con transformador (medición semidirecta en el secundario)
Para instalaciones donde el transformador va antes de la medición:
```
unifilar 13200v 3 cortacircuitos transformador bifasico 20 kva 2 tc 200/5 totalizador 200 amp
```
Genera: RED MT -> N cortacircuitos -> transformador -> barra BT -> N TC -> medidor (I de TC + V directa) -> totalizador/interruptor -> carga.
Parámetros detectados del texto: kVA, tipo (bi/mono/trifásico), nº de cortacircuitos, nº de TC, relación de TC y amperaje del totalizador.

## Fuente de simbología
Norma **UNE/IEC 60617**. Referencia divulgativa: instrumentacionhoy.blogspot.com (unifilar).
# BotElectrical
# BotElectrical
