"""
Script de configuracion: sube TODOS los documentos de retie_docs/ al
API de Gemini (Files API) y crea un Context Cache reutilizable.

El cache guarda el contexto de todos los documentos pre-procesados para
que cada consulta sea mas rapida y economica (no repite la lectura de PDFs).

USO:
    1. Pon todos los PDFs/TXTs en la carpeta retie_docs/
    2. export GEMINI_API_KEY="tu_api_key"
    3. python setup_retie_store.py

Al final imprime el nombre del cache. Copia ese valor como variable de
entorno RETIE_CACHE_NAME en Render (o en tu .env local).

RENOVACION: Los caches de Gemini expiran. Ejecuta este script de nuevo
cuando el cache expire o cuando agregues documentos nuevos.
"""

import os, time, shutil, unicodedata, mimetypes
from pathlib import Path
from google import genai
from google.genai import types

DOCS_DIR      = "retie_docs"
GEMINI_MODEL  = "gemini-2.5-flash"
CACHE_TTL     = "86400s"   # 24 horas (max permitido: 1 hora por defecto, se puede extender)
CACHE_DISPLAY = "retie-docs-cache"

# Extensiones soportadas por la Files API de Gemini
EXTS_VALIDAS = {".pdf", ".txt", ".md", ".docx"}

# Archivos a NO subir (imágenes, duplicados, temporales)
ARCHIVOS_EXCLUIR = {
    "Captura de pantalla 2026-06-15 a la(s) 12.29.26 p.m..png",
    "IMG-20210112-WA0001.jpg",
    "IMG_20211212_075914875.jpg",
    "D-019-14 ACTUALIZACIoN CoDIGO DE MEDIDA (1).pdf",  # duplicado
}

MIME_MAP = {
    ".pdf":  "application/pdf",
    ".txt":  "text/plain",
    ".md":   "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def ascii_safe_name(name: str) -> str:
    """Quita tildes y caracteres especiales para nombres de archivo ASCII."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).encode(
        "ascii", "ignore"
    ).decode("ascii")


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: define la variable de entorno GEMINI_API_KEY primero.")

    docs_path = Path(DOCS_DIR)
    if not docs_path.exists():
        raise SystemExit(f"ERROR: carpeta '{DOCS_DIR}' no existe.")

    archivos = [
        f for f in sorted(docs_path.iterdir())
        if f.is_file()
        and f.suffix.lower() in EXTS_VALIDAS
        and f.name not in ARCHIVOS_EXCLUIR
    ]
    if not archivos:
        raise SystemExit(f"ERROR: no hay documentos validos en '{DOCS_DIR}'.")

    print(f"Documentos a indexar ({len(archivos)}):")
    for f in archivos:
        print(f"   [{f.suffix}] {f.name}")
    print()

    client = genai.Client(api_key=api_key)

    # ── 1. Subir archivos a la Files API ──────────────────────────────────────
    print("1. Subiendo documentos a la Files API de Gemini...")
    tmp_dir = docs_path / "_tmp_ascii"
    tmp_dir.mkdir(exist_ok=True)

    uploaded_files = []
    for i, f in enumerate(archivos, 1):
        safe_name = ascii_safe_name(f.stem).replace(" ", "_") or f"doc_{i}"
        safe_path = tmp_dir / f"{safe_name}{f.suffix.lower()}"
        shutil.copyfile(f, safe_path)

        mime = MIME_MAP.get(f.suffix.lower(), "application/octet-stream")
        print(f"   [{i}/{len(archivos)}] {f.name} ...", end="", flush=True)
        try:
            gfile = client.files.upload(
                file=str(safe_path),
                config={"display_name": safe_name, "mime_type": mime},
            )
            # Esperar a que el archivo este listo
            for _ in range(30):
                gfile = client.files.get(name=gfile.name)
                if gfile.state and gfile.state.name != "PROCESSING":
                    break
                time.sleep(3)
            uploaded_files.append(gfile)
            print(f" OK  ({gfile.name})")
        except Exception as e:
            print(f" ERROR: {e}")
        finally:
            safe_path.unlink(missing_ok=True)

    try:
        tmp_dir.rmdir()
    except Exception:
        pass

    if not uploaded_files:
        raise SystemExit("ERROR: no se pudo subir ningun archivo.")

    print(f"\nSubidos {len(uploaded_files)} de {len(archivos)} documentos.")

    # ── 2. Crear Context Cache ─────────────────────────────────────────────────
    print("\n2. Creando Context Cache con todos los documentos...")

    # Construir los parts con los archivos
    parts = []
    for gf in uploaded_files:
        parts.append(types.Part(
            file_data=types.FileData(file_uri=gf.uri, mime_type=gf.mime_type)
        ))

    # Agregar instruccion inicial como contexto
    parts.append(types.Part(text=(
        "Estos documentos son tu base de conocimiento normativo sobre energia electrica "
        "en Colombia: RETIE 2024, CREG, NTC 2050, trabajo en alturas, calidad de energia, "
        "subestaciones y medida de energia. Usa estos documentos para responder consultas "
        "tecnicas con precision normativa."
    )))

    try:
        cache = client.caches.create(
            model=GEMINI_MODEL,
            config=types.CreateCachedContentConfig(
                display_name=CACHE_DISPLAY,
                contents=[types.Content(role="user", parts=parts)],
                ttl=CACHE_TTL,
            )
        )

        print(f"\n{'='*60}")
        print("CACHE CREADO EXITOSAMENTE")
        print(f"{'='*60}")
        print(f"\nNombre del cache: {cache.name}")
        print(f"Vence:            {cache.expire_time}")
        print()
        print("AGREGA ESTA VARIABLE DE ENTORNO EN RENDER:")
        print()
        print(f'    RETIE_CACHE_NAME="{cache.name}"')
        print()
        print("Cuando el cache expire, vuelve a correr este script.")
        print(f"{'='*60}")

    except Exception as e:
        print(f"ERROR al crear cache: {e}")
        print()
        print("Los archivos fueron subidos. URIs de archivos (para uso alternativo):")
        for gf in uploaded_files:
            print(f"   {gf.name}: {gf.uri}")


if __name__ == "__main__":
    main()
