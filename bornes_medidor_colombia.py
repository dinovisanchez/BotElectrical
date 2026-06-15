# -*- coding: utf-8 -*-
"""
=============================================================================
DOCUMENTACIÓN TÉCNICA — BORNES DE MEDIDOR ELÉCTRICO EN COLOMBIA
=============================================================================
Normativa:  RETIE 2024 (Resolución 40117 de 2024)
            CREG 038/2014 — Código de Medida
            NTC 2050 — Código Eléctrico Colombiano
Operadores: Enel/Codensa · EPM · Afinia
Revisión:   2026-06-15
=============================================================================

DEFINICIONES DE CONEXIÓN:
──────────────────────────────────────────────────────────────────────────────
SIMÉTRICA  : Los conductores se cruzan en la bornera (patrón espejo).
             La última línea en salir es la primera en entrar.
             Monofásico: F_in → N_sal → N_ent → F_sal  (1-2-3-4)
             Trifásico:  R-S-T-N de entrada | N-T-S-R de salida (espejo)

ASIMÉTRICA : Los conductores mantienen orden secuencial (patrón en línea recta).
             Cada línea que entra al medidor sale en el borne inmediatamente siguiente.
             Monofásico: F_in → F_sal → N_ent → N_sal  (1-2-3-4)
             Trifásico:  Rentrada-Rsalida-Sentrada-Ssalida-Tentrada-Tsalida-Nentrada-Nsalida
──────────────────────────────────────────────────────────────────────────────
"""

# =============================================================================
# SECCIÓN 1 — CÓDIGO DE COLORES OFICIAL COLOMBIA
# RETIE 2024, Libro 3, Título 5 / NTC 2050 Tabla 310-12
# =============================================================================
COLORES_CONDUCTOR = {
    "fase_R": {
        "nombre":    "Rojo",
        "hex":       "#D32F2F",
        "aplicacion": "Fase R / L1 / Polo A",
        "norma":     "RETIE 2024, Lib.3 Tít.5",
    },
    "fase_S": {
        "nombre":    "Amarillo",
        "hex":       "#F9A825",
        "aplicacion": "Fase S / L2 / Polo B",
        "norma":     "RETIE 2024, Lib.3 Tít.5",
    },
    "fase_T": {
        "nombre":    "Azul",
        "hex":       "#1565C0",
        "aplicacion": "Fase T / L3 / Polo C",
        "norma":     "RETIE 2024, Lib.3 Tít.5",
    },
    "neutro": {
        "nombre":    "Blanco",
        "hex":       "#ECEFF1",
        "aplicacion": "Conductor neutro (N)",
        "norma":     "RETIE 2024, Lib.3 Tít.5",
    },
    "tierra": {
        "nombre":    "Verde / Verde-Amarillo",
        "hex":       "#2E7D32",
        "aplicacion": "Tierra de protección (PE) — NUNCA conectar a bornes del medidor",
        "norma":     "RETIE 2024, Lib.3 Tít.5",
    },
}

# =============================================================================
# SECCIÓN 2 — CALIBRES MÍNIMOS DE CONDUCTOR
# RETIE 2024, Libro 3 / NTC 2050 Tabla 310-16
# =============================================================================
CALIBRES_CONDUCTOR_CU = {
    # Corriente : AWG / sección mínima cobre
    "15 A":  {"awg": "14", "mm2": 2.08,  "uso": "Iluminación y tomacorrientes"},
    "20 A":  {"awg": "12", "mm2": 3.31,  "uso": "Cocina, lavadora, tomacorrientes 20A"},
    "30 A":  {"awg": "10", "mm2": 5.26,  "uso": "Secadora, A/A residencial"},
    "50 A":  {"awg": "8",  "mm2": 8.37,  "uso": "Acometida residencial pequeña"},
    "70 A":  {"awg": "6",  "mm2": 13.3,  "uso": "Acometida residencial media"},
    "100 A": {"awg": "4",  "mm2": 21.15, "uso": "Acometida residencial grande"},
    "150 A": {"awg": "1",  "mm2": 42.4,  "uso": "Acometida comercial pequeña"},
    "200 A": {"awg": "3/0","mm2": 85.0,  "uso": "Acometida industrial / comercial media"},
}

# =============================================================================
# SECCIÓN 3 — BORNES MONOFÁSICO (4 bornes)
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# 3.1  MONOFÁSICO — CONEXIÓN SIMÉTRICA
#
#  Vista de la bornera (izquierda → derecha):
#
#  ACOMETIDA                                        CARGA
#  ─────────                                        ─────
#  Fase R ──→ ┌─────┬─────┬─────┬─────┐ ──→ Fase R
#             │  1  │  2  │  3  │  4  │
#             │ F▶  │ N◀  │ N▶  │ F◀  │
#  Neutro ──→ └──│──┘  └──│──┘  └──│──┘ ──→ Neutro
#
#   F▶ = Fase entrada  (red)     N◀ = Neutro salida (carga)
#   N▶ = Neutro entrada (red)    F◀ = Fase salida  (carga)
#
#  Los conductores se cruzan: la fase entra por el extremo opuesto
#  al que sale. El neutro hace el recorrido contrario.
# ─────────────────────────────────────────────────────────────────────────────
MONO_SIMETRICA = {
    "descripcion":  "Monofásico 2 hilos — Conexión simétrica (bornes cruzados/espejo)",
    "fases":        1,
    "total_bornes": 4,
    "diagrama_ascii": """
    ACOMETIDA              MEDIDOR              CARGA
    ─────────    ┌──────────────────────┐    ─────────
    Fase R ─────►│ 1 [F_ent]  [F_sal] 4 │────► Fase R
                 │     ╲            ╱   │
                 │      ╲ (cruzado) ╱   │
                 │     ╱            ╲   │
    Neutro ─────►│ 3 [N_ent]  [N_sal] 2 │────► Neutro
                 └──────────────────────┘
    """,
    "bornes": {
        1: {
            "funcion":    "Fase R — Entrada",
            "conductor":  "fase_R",
            "color":      "Rojo",
            "conexion":   "Acometida → Borne 1",
            "tipo":       "ENTRADA",
            "nota":       "Fase de la red. Corriente entra por aquí al medidor.",
        },
        2: {
            "funcion":    "Neutro — Salida",
            "conductor":  "neutro",
            "color":      "Blanco",
            "conexion":   "Borne 2 → Carga interna",
            "tipo":       "SALIDA",
            "nota":       "Neutro hacia la instalación del usuario. Patrón cruzado: "
                          "salida de neutro está junto a la entrada de fase.",
        },
        3: {
            "funcion":    "Neutro — Entrada",
            "conductor":  "neutro",
            "color":      "Blanco",
            "conexion":   "Acometida → Borne 3",
            "tipo":       "ENTRADA",
            "nota":       "Neutro de la red de distribución.",
        },
        4: {
            "funcion":    "Fase R — Salida",
            "conductor":  "fase_R",
            "color":      "Rojo",
            "conexion":   "Borne 4 → Carga interna",
            "tipo":       "SALIDA",
            "nota":       "Fase hacia la instalación del usuario. Patrón cruzado: "
                          "salida de fase está junto a la entrada de neutro.",
        },
    },
    "advertencias_retie": [
        "⚠️  RETIE 2024, Art. 15: El medidor debe ser instalado por personal certificado.",
        "⚠️  Calibre mínimo: AWG 14 (2.08 mm²) para 15 A — NTC 2050 Tabla 310-16.",
        "⚠️  Aislamiento mínimo 600 V tipo THHN, THWN o equivalente.",
        "⚠️  NO conectar tierra de protección (verde) en bornes del medidor.",
        "⚠️  El precinto de seguridad es de exclusiva instalación del operador de red.",
        "⚠️  Verificar polaridad con multímetro antes de energizar (Fase en 1, Neutro en 3).",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# 3.2  MONOFÁSICO — CONEXIÓN ASIMÉTRICA
#
#  Vista de la bornera:
#
#  ACOMETIDA                                        CARGA
#  ─────────                                        ─────
#  Fase R ──→ ┌─────┬─────┬─────┬─────┐ ──→ Fase R
#             │  1  │  2  │  3  │  4  │
#             │ F▶  │ F◀  │ N▶  │ N◀  │
#  Neutro ──→ └─────┴─────┴─────┴─────┘ ──→ Neutro
#
#  F▶ = Fase entrada   F◀ = Fase salida
#  N▶ = Neutro entrada N◀ = Neutro salida
#
#  Cada conductor entra y sale en bornes contiguos — sin cruzar.
# ─────────────────────────────────────────────────────────────────────────────
MONO_ASIMETRICA = {
    "descripcion":  "Monofásico 2 hilos — Conexión asimétrica (bornes secuenciales/en línea)",
    "fases":        1,
    "total_bornes": 4,
    "diagrama_ascii": """
    ACOMETIDA              MEDIDOR              CARGA
    ─────────    ┌──────────────────────┐    ─────────
    Fase R ─────►│ 1 [F_ent]  [F_sal] 2 │────► Fase R
                 │     │              │  │
                 │     │ (en línea)   │  │
                 │     │              │  │
    Neutro ─────►│ 3 [N_ent]  [N_sal] 4 │────► Neutro
                 └──────────────────────┘
    """,
    "bornes": {
        1: {
            "funcion":    "Fase R — Entrada",
            "conductor":  "fase_R",
            "color":      "Rojo",
            "conexion":   "Acometida → Borne 1",
            "tipo":       "ENTRADA",
            "nota":       "Fase de la red. El conductor viene directo de la acometida.",
        },
        2: {
            "funcion":    "Fase R — Salida",
            "conductor":  "fase_R",
            "color":      "Rojo",
            "conexion":   "Borne 2 → Carga interna",
            "tipo":       "SALIDA",
            "nota":       "Fase hacia la instalación. Contiguo al borne 1 — sin cruzar.",
        },
        3: {
            "funcion":    "Neutro — Entrada",
            "conductor":  "neutro",
            "color":      "Blanco",
            "conexion":   "Acometida → Borne 3",
            "tipo":       "ENTRADA",
            "nota":       "Neutro de la red. Separado del grupo de fase.",
        },
        4: {
            "funcion":    "Neutro — Salida",
            "conductor":  "neutro",
            "color":      "Blanco",
            "conexion":   "Borne 4 → Carga interna",
            "tipo":       "SALIDA",
            "nota":       "Neutro hacia la instalación. Contiguo al borne 3 — sin cruzar.",
        },
    },
    "advertencias_retie": MONO_SIMETRICA["advertencias_retie"],
}

# =============================================================================
# SECCIÓN 4 — BORNES TRIFÁSICO 4 HILOS (8 bornes)
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# 4.1  TRIFÁSICO 4H — CONEXIÓN SIMÉTRICA (patrón espejo)
#
#  Vista de la bornera (izquierda → derecha):
#
#  ACOMETIDA  ┌────┬────┬────┬────┬────┬────┬────┬────┐  CARGA
#  Fase R ────│ 1  │ 2  │ 3  │ 4  ║ 5  │ 6  │ 7  │ 8  │──── Fase R
#  Fase S ────│ Re │ Se │ Te │ Ne ║ Ns │ Ts │ Ss │ Rs │──── Fase S
#  Fase T ────│    │    │    │    ║    │    │    │    │──── Fase T
#  Neutro ────│    │    │    │    ║    │    │    │    │──── Neutro
#             └────┴────┴────┴────╨────┴────┴────┴────┘
#              ◄──── ENTRADAS ────►◄──── SALIDAS ────►
#              ◄────────────── ESPEJO ───────────────►
#                              (R→8, S→7, T→6, N→5)
# ─────────────────────────────────────────────────────────────────────────────
TRI4H_SIMETRICA = {
    "descripcion":  "Trifásico 4 hilos — Conexión simétrica (patrón espejo, 8 bornes)",
    "fases":        3,
    "total_bornes": 8,
    "diagrama_ascii": """
    ACOMETIDA                    MEDIDOR                    CARGA
    ─────────    ┌────────────────────────────────────┐    ─────────
    Fase R ─────►│ 1[Re]  2[Se]  3[Te]  4[Ne]         │
                 │                  ╲ ╲ ╲ ╲  (espejo)  │
    Fase S ─────►│                   ╲ ╲ ╲ ╲           │────► Fase R (borne 8)
                 │                    ╲ ╲ ╲ ╲          │────► Fase S (borne 7)
    Fase T ─────►│         5[Ns]  6[Ts]  7[Ss]  8[Rs] │────► Fase T (borne 6)
    Neutro ─────►│                                     │────► Neutro (borne 5)
                 └────────────────────────────────────┘
    Espejo: Borne 1(Re)↔8(Rs) | 2(Se)↔7(Ss) | 3(Te)↔6(Ts) | 4(Ne)↔5(Ns)
    """,
    "bornes": {
        1: {
            "funcion":    "Fase R — Entrada",
            "conductor":  "fase_R",
            "color":      "Rojo",
            "conexion":   "Acometida R → Borne 1",
            "tipo":       "ENTRADA",
            "nota":       "Primera fase de la acometida. Polo A. Espejo con borne 8.",
        },
        2: {
            "funcion":    "Fase S — Entrada",
            "conductor":  "fase_S",
            "color":      "Amarillo",
            "conexion":   "Acometida S → Borne 2",
            "tipo":       "ENTRADA",
            "nota":       "Segunda fase de la acometida. Polo B. Espejo con borne 7.",
        },
        3: {
            "funcion":    "Fase T — Entrada",
            "conductor":  "fase_T",
            "color":      "Azul",
            "conexion":   "Acometida T → Borne 3",
            "tipo":       "ENTRADA",
            "nota":       "Tercera fase de la acometida. Polo C. Espejo con borne 6.",
        },
        4: {
            "funcion":    "Neutro — Entrada",
            "conductor":  "neutro",
            "color":      "Blanco",
            "conexion":   "Acometida N → Borne 4",
            "tipo":       "ENTRADA",
            "nota":       "Neutro de la acometida. Centro del espejo con borne 5.",
        },
        5: {
            "funcion":    "Neutro — Salida",
            "conductor":  "neutro",
            "color":      "Blanco",
            "conexion":   "Borne 5 → Tablero / Carga",
            "tipo":       "SALIDA",
            "nota":       "Neutro hacia la instalación. Espejo del borne 4.",
        },
        6: {
            "funcion":    "Fase T — Salida",
            "conductor":  "fase_T",
            "color":      "Azul",
            "conexion":   "Borne 6 → Tablero / Carga",
            "tipo":       "SALIDA",
            "nota":       "Fase T hacia la instalación. Espejo del borne 3.",
        },
        7: {
            "funcion":    "Fase S — Salida",
            "conductor":  "fase_S",
            "color":      "Amarillo",
            "conexion":   "Borne 7 → Tablero / Carga",
            "tipo":       "SALIDA",
            "nota":       "Fase S hacia la instalación. Espejo del borne 2.",
        },
        8: {
            "funcion":    "Fase R — Salida",
            "conductor":  "fase_R",
            "color":      "Rojo",
            "conexion":   "Borne 8 → Tablero / Carga",
            "tipo":       "SALIDA",
            "nota":       "Fase R hacia la instalación. Espejo del borne 1.",
        },
    },
    "advertencias_retie": [
        "⚠️  Verificar secuencia de fases R-S-T con fasímetro ANTES de energizar — RETIE Lib.3.",
        "⚠️  Calibre mínimo para acometida trifásica: AWG 8 (8.37 mm²) para 50 A — NTC 2050.",
        "⚠️  Identificar cada conductor con cinta o tubete del color correspondiente (RETIE Tít.5).",
        "⚠️  En medida directa trifásica: corriente máxima típica 100 A. Por encima usar TC.",
        "⚠️  Par de apriete de terminales: 2.5 N·m hasta 35 mm² / 5 N·m hasta 95 mm² (Cu).",
        "⚠️  El operador de red fija el sello y precinto — NO retirar sin autorización escrita.",
        "⚠️  PROHIBIDO manipular bornes del medidor. Infracción tipificada en Ley 142/1994.",
    ],
    "operadores": {
        "Enel_Codensa": {
            "zona":              "Bogotá D.C. y Cundinamarca",
            "norma_especifica":  "RET-CODENSA-ET-001 / NTC 2967",
            "calibre_min_50A":   "AWG 8 (8.37 mm²) THHN cobre",
            "notas_campo":       "Sello de seguridad tipo Destral en todos los bornes. "
                                 "Caja tipo IPC-1 con cerradura de seguridad.",
        },
        "EPM": {
            "zona":              "Medellín, Antioquia y municipios",
            "norma_especifica":  "ET-EPM-G1-001 / NET-ET-110",
            "calibre_min_50A":   "AWG 8 (8.37 mm²) THWN cobre",
            "notas_campo":       "Caja metálica con puerta de vidrio. "
                                 "Medidores homologados: Itron, Elster, Landis+Gyr.",
        },
        "Afinia": {
            "zona":              "Costa Atlántica, Eje Cafetero (antes Electricaribe)",
            "norma_especifica":  "ET-AFINIA-GD-002",
            "calibre_min_50A":   "AWG 10 (5.26 mm²) THHN cobre mínimo",
            "notas_campo":       "En zonas rurales puede aplicar medición monofásica "
                                 "aunque la red sea trifásica. Verificar en obra.",
        },
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# 4.2  TRIFÁSICO 4H — CONEXIÓN ASIMÉTRICA (patrón secuencial)
#
#  Vista de la bornera (izquierda → derecha):
#
#  ACOMETIDA  ┌────┬────┬────┬────┬────┬────┬────┬────┐  CARGA
#             │ 1  │ 2  │ 3  │ 4  │ 5  │ 6  │ 7  │ 8  │
#             │ Re │ Rs │ Se │ Ss │ Te │ Ts │ Ne │ Ns │
#             └────┴────┴────┴────┴────┴────┴────┴────┘
#              ├──R──┤ ├──S──┤ ├──T──┤ ├──N──┤
#              cada par entra y sale en bornes contiguos
# ─────────────────────────────────────────────────────────────────────────────
TRI4H_ASIMETRICA = {
    "descripcion":  "Trifásico 4 hilos — Conexión asimétrica (patrón secuencial, 8 bornes)",
    "fases":        3,
    "total_bornes": 8,
    "diagrama_ascii": """
    ACOMETIDA                    MEDIDOR                    CARGA
    ─────────    ┌────────────────────────────────────┐    ─────────
    Fase R ─────►│ 1[Re] 2[Rs] │ 3[Se] 4[Ss] │ ...   │────► Fase R (borne 2)
    Fase S ─────►│             │             │        │────► Fase S (borne 4)
    Fase T ─────►│ ... 5[Te] 6[Ts] │ 7[Ne] 8[Ns]    │────► Fase T (borne 6)
    Neutro ─────►│                                    │────► Neutro (borne 8)
                 └────────────────────────────────────┘
    Pares: (1-2)=R | (3-4)=S | (5-6)=T | (7-8)=N  — sin cruzar
    """,
    "bornes": {
        1: {
            "funcion":    "Fase R — Entrada",
            "conductor":  "fase_R",
            "color":      "Rojo",
            "conexion":   "Acometida R → Borne 1",
            "tipo":       "ENTRADA",
            "nota":       "Fase R de la red. Par (1-2) = fase R completa.",
        },
        2: {
            "funcion":    "Fase R — Salida",
            "conductor":  "fase_R",
            "color":      "Rojo",
            "conexion":   "Borne 2 → Tablero / Carga",
            "tipo":       "SALIDA",
            "nota":       "Fase R hacia la instalación. Contiguo al borne 1.",
        },
        3: {
            "funcion":    "Fase S — Entrada",
            "conductor":  "fase_S",
            "color":      "Amarillo",
            "conexion":   "Acometida S → Borne 3",
            "tipo":       "ENTRADA",
            "nota":       "Fase S de la red. Par (3-4) = fase S completa.",
        },
        4: {
            "funcion":    "Fase S — Salida",
            "conductor":  "fase_S",
            "color":      "Amarillo",
            "conexion":   "Borne 4 → Tablero / Carga",
            "tipo":       "SALIDA",
            "nota":       "Fase S hacia la instalación. Contiguo al borne 3.",
        },
        5: {
            "funcion":    "Fase T — Entrada",
            "conductor":  "fase_T",
            "color":      "Azul",
            "conexion":   "Acometida T → Borne 5",
            "tipo":       "ENTRADA",
            "nota":       "Fase T de la red. Par (5-6) = fase T completa.",
        },
        6: {
            "funcion":    "Fase T — Salida",
            "conductor":  "fase_T",
            "color":      "Azul",
            "conexion":   "Borne 6 → Tablero / Carga",
            "tipo":       "SALIDA",
            "nota":       "Fase T hacia la instalación. Contiguo al borne 5.",
        },
        7: {
            "funcion":    "Neutro — Entrada",
            "conductor":  "neutro",
            "color":      "Blanco",
            "conexion":   "Acometida N → Borne 7",
            "tipo":       "ENTRADA",
            "nota":       "Neutro de la red. Par (7-8) = neutro completo.",
        },
        8: {
            "funcion":    "Neutro — Salida",
            "conductor":  "neutro",
            "color":      "Blanco",
            "conexion":   "Borne 8 → Tablero / Carga",
            "tipo":       "SALIDA",
            "nota":       "Neutro hacia la instalación. Contiguo al borne 7.",
        },
    },
    "advertencias_retie": TRI4H_SIMETRICA["advertencias_retie"],
    "operadores": TRI4H_SIMETRICA["operadores"],
}

# =============================================================================
# SECCIÓN 5 — ÍNDICE DE CONFIGURACIONES
# =============================================================================
CONFIGURACIONES = {
    ("mono",  "simetrica"):  MONO_SIMETRICA,
    ("mono",  "asimetrica"): MONO_ASIMETRICA,
    ("tri4h", "simetrica"):  TRI4H_SIMETRICA,
    ("tri4h", "asimetrica"): TRI4H_ASIMETRICA,
}

# =============================================================================
# SECCIÓN 6 — FUNCIONES DE CONSULTA Y VALIDACIÓN
# =============================================================================

def get_config(sistema: str, conexion: str) -> dict:
    """
    Retorna la configuración de bornes para el sistema y conexión indicados.

    Args:
        sistema  : 'mono'  — monofásico 2H (4 bornes)
                   'tri4h' — trifásico 4H  (8 bornes)
        conexion : 'simetrica'  — patrón espejo/cruzado
                   'asimetrica' — patrón secuencial/en línea

    Returns:
        dict completo con bornes, colores, advertencias RETIE y notas operadores.

    Raises:
        ValueError si los parámetros no son válidos.
    """
    key = (sistema.strip().lower(), conexion.strip().lower())
    if key not in CONFIGURACIONES:
        validas = list(CONFIGURACIONES.keys())
        raise ValueError(
            f"Combinación no reconocida: sistema='{sistema}', conexion='{conexion}'.\n"
            f"Válidas: {validas}"
        )
    return CONFIGURACIONES[key]


def imprimir_bornes(sistema: str, conexion: str) -> None:
    """Imprime la tabla de bornes en consola con formato legible."""
    cfg = get_config(sistema, conexion)

    RESET = "\033[0m"
    BOLD  = "\033[1m"
    COLORES_ANSI = {
        "Rojo":    "\033[91m",
        "Amarillo":"\033[93m",
        "Azul":    "\033[94m",
        "Blanco":  "\033[97m",
    }

    print(f"\n{'═'*70}")
    print(f"  {BOLD}{cfg['descripcion'].upper()}{RESET}")
    print(f"{'═'*70}")
    print(f"  Fases: {cfg['fases']}   ·   Total bornes: {cfg['total_bornes']}")
    print(f"\n  {'Borne':<7} {'Función':<25} {'Color':<10} {'Tipo':<9} {'Conexión'}")
    print(f"  {'─'*65}")
    for num, b in cfg["bornes"].items():
        col_ansi = COLORES_ANSI.get(b["color"], "")
        color_txt = f"{col_ansi}■ {b['color']}{RESET}"
        print(f"  {num:<7} {b['funcion']:<25} {color_txt:<20} {b['tipo']:<9} {b['conexion']}")
    print(f"\n  {'─'*65}")
    print(f"  {BOLD}ADVERTENCIAS RETIE 2024:{RESET}")
    for adv in cfg["advertencias_retie"]:
        print(f"  {adv}")
    print(f"{'═'*70}\n")


def validar_conexion(sistema: str, conexion: str, bornes_usuario: dict) -> list:
    """
    Valida que la asignación de bornes del usuario sea correcta.

    Args:
        sistema, conexion : igual que get_config()
        bornes_usuario : dict {num_borne: "descripcion_del_usuario"}
                         Ej: {1: "fase roja red", 2: "neutro carga", ...}

    Returns:
        list de str con errores encontrados (vacío si todo OK).
    """
    cfg    = get_config(sistema, conexion)
    errores = []
    for num, desc_usuario in bornes_usuario.items():
        if num not in cfg["bornes"]:
            errores.append(f"Borne {num} no existe en configuración {sistema}/{conexion}.")
            continue
        esperado = cfg["bornes"][num]
        desc_low = desc_usuario.lower()
        # Verificar tipo (entrada/salida)
        tipo_ok = esperado["tipo"].lower() in desc_low
        # Verificar conductor (fase/neutro)
        cond_ok = any(
            keyword in desc_low
            for keyword in [
                esperado["conductor"].replace("_", " "),
                esperado["color"].lower(),
                "fase" if "fase" in esperado["funcion"].lower() else "neutro",
            ]
        )
        if not tipo_ok or not cond_ok:
            errores.append(
                f"Borne {num}: se esperaba '{esperado['funcion']}' "
                f"({esperado['tipo']}, color {esperado['color']}) — "
                f"pero se recibió: '{desc_usuario}'."
            )
    return errores


# =============================================================================
# SECCIÓN 7 — PUNTO DE ENTRADA (DEMO)
# =============================================================================
if __name__ == "__main__":
    print("\n" + "="*70)
    print("  DEMOSTRACIÓN — CONFIGURACIONES DE BORNES PARA COLOMBIA (RETIE 2024)")
    print("="*70)

    for (sis, con) in CONFIGURACIONES:
        imprimir_bornes(sis, con)

    # Ejemplo de validación
    print("EJEMPLO DE VALIDACIÓN:")
    print("─"*40)
    errores = validar_conexion(
        sistema="mono",
        conexion="simetrica",
        bornes_usuario={
            1: "fase roja entrada red",
            2: "neutro blanco salida carga",
            3: "neutro blanco entrada red",
            4: "fase roja salida carga",
        }
    )
    if errores:
        print("❌ Errores encontrados:")
        for e in errores: print(f"   • {e}")
    else:
        print("✅ Conexión correcta según RETIE 2024.")
