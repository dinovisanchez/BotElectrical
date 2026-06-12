"""
Script de configuracion UNICA: sube TODOS los PDFs (y otros documentos)
de una carpeta a un File Search Store de Gemini, para que DinoBot pueda
consultarlos en cada pregunta sin necesidad de volver a subirlos.

USO:
    1. Crea una carpeta (por ejemplo "retie_docs") y coloca DENTRO todos
       los documentos que quieres que el bot pueda consultar:
         - Resolucion 40117 de 2024 (RETIE)
         - Cualquier anexo, norma adicional, manual interno, etc.
       Pueden ser varios PDFs, .docx, .txt, etc. - todos se indexan juntos.

    2. export GEMINI_API_KEY="tu_api_key"
    3. pip install google-genai
    4. python setup_retie_store.py
       (si tu carpeta no se llama "retie_docs", ajusta DOCS_DIR abajo)

Al final imprime el "store name" (algo como "fileSearchStores/xxxxx").
Copia ese valor y pegalo como variable de entorno RETIE_STORE_NAME
(o directamente en bot.py).

Este script solo se corre UNA VEZ. Si despues quieres AGREGAR mas
documentos al MISMO store ya creado, vuelve a correr el script pero
pon el store_name existente en EXISTING_STORE_NAME (linea de abajo)
para no crear un store duplicado.
"""

import os
import time
import shutil
import unicodedata
from pathlib import Path
from google import genai

DOCS_DIR = "retie_docs"          # <-- Carpeta con TODOS tus documentos (PDFs, etc.)
STORE_DISPLAY_NAME = "retie-2024"

# Si ya tienes un store creado y solo quieres AGREGAR documentos nuevos,
# pega aqui su nombre (ej: "fileSearchStores/abc123") y se reutilizara
# en vez de crear uno nuevo.
EXISTING_STORE_NAME = ""

# Extensiones soportadas por File Search (las mas comunes)
EXTS_VALIDAS = {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".html", ".xml"}


def ascii_safe_name(name: str) -> str:
    """Quita tildes/caracteres especiales para evitar errores de codificacion
    ASCII al enviar el display_name como cabecera HTTP."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).encode(
        "ascii", "ignore"
    ).decode("ascii")


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: define la variable de entorno GEMINI_API_KEY primero.")

    docs_path = Path(DOCS_DIR)
    if not docs_path.exists() or not docs_path.is_dir():
        raise SystemExit(
            f"ERROR: no encuentro la carpeta '{DOCS_DIR}'. "
            f"Crea esa carpeta y pon dentro todos tus PDFs/documentos, "
            f"o ajusta DOCS_DIR en este script."
        )

    archivos = [
        f for f in sorted(docs_path.iterdir())
        if f.is_file() and f.suffix.lower() in EXTS_VALIDAS
    ]
    if not archivos:
        raise SystemExit(
            f"ERROR: no encontre archivos validos ({', '.join(EXTS_VALIDAS)}) "
            f"dentro de '{DOCS_DIR}'."
        )

    print(f"Encontrados {len(archivos)} documentos para indexar:")
    for f in archivos:
        print(f"   - {f.name}")
    print()

    client = genai.Client(api_key=api_key)

    if EXISTING_STORE_NAME:
        print(f"Usando store existente: {EXISTING_STORE_NAME}")
        store_name = EXISTING_STORE_NAME
    else:
        print(f"1. Creando File Search Store '{STORE_DISPLAY_NAME}'...")
        store = client.file_search_stores.create(
            config={"display_name": STORE_DISPLAY_NAME}
        )
        store_name = store.name
        print(f"   Store creado: {store_name}")
        print(f"   (Si el script falla mas adelante, vuelve a correrlo poniendo")
        print(f"    EXISTING_STORE_NAME = \"{store_name}\" para no duplicar el store)")

    print()
    print("2. Subiendo e indexando documentos (puede tardar varios minutos)...")
    tmp_dir = docs_path / "_tmp_ascii"
    tmp_dir.mkdir(exist_ok=True)
    for i, f in enumerate(archivos, 1):
        print(f"   [{i}/{len(archivos)}] {f.name} ...")

        # Copia temporal con nombre 100% ASCII (sin tildes/espacios), porque
        # la libreria usa el nombre de archivo en cabeceras HTTP que solo
        # aceptan ASCII.
        safe_stem = ascii_safe_name(f.stem).replace(" ", "_") or f"doc_{i}"
        safe_path = tmp_dir / f"{safe_stem}{f.suffix.lower()}"
        shutil.copyfile(f, safe_path)

        try:
            operation = client.file_search_stores.upload_to_file_search_store(
                file=str(safe_path),
                file_search_store_name=store_name,
                config={"display_name": safe_stem},
            )
            while not operation.done:
                time.sleep(5)
                operation = client.operations.get(operation)
        finally:
            safe_path.unlink(missing_ok=True)
        print(f"        OK")

    tmp_dir.rmdir()

    print()
    print("3. Indexacion completa de todos los documentos.")
    print()
    print("=" * 60)
    print("COPIA ESTE VALOR y usalo como variable de entorno RETIE_STORE_NAME:")
    print()
    print(f'    export RETIE_STORE_NAME="{store_name}"')
    print()
    print("(o pegalo directamente en bot.py en RETIE_STORE_NAME)")
    print("=" * 60)


if __name__ == "__main__":
    main()
