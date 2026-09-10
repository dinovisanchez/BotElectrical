#!/usr/bin/env python3
"""Crea (o reutiliza) un Gemini File Search Store y sube documentos
normativos (RETIE, CREG) para que el bot busque en el TEXTO REAL de la
norma en vez de depender solo de los "datos memorizados" en el prompt
de bot.py (PROMPT_SISTEMA_RETIE).

Uso:
    export GEMINI_API_KEY="tu-api-key"

    # Primera vez (crea el store):
    python3 setup_retie_store.py normativa/RETIE_2024_compilado.pdf normativa/CREG_038_2014.pdf ...

    # Para agregar mas documentos despues (reutiliza el store existente,
    # no borra lo que ya habia):
    export RETIE_STORE_NAME="fileSearchStores/xxxxx"   # el que imprimio la corrida anterior
    python3 setup_retie_store.py normativa/CREG_015_2018.pdf

Al terminar imprime el nombre del store. Ese valor va en la variable de
entorno RETIE_STORE_NAME del bot (en Render: Environment Variables del
servicio) -- bot.py ya lee esa variable y activa la busqueda (ver
_consulta_retie en bot.py).

Documentos recomendados (fuente oficial, descargalos antes de correr esto):
  - RETIE 2024 compilado (con la modificacion de 2026 ya incorporada):
    https://www.minenergia.gov.co/documents/15918/Resolucion-40284-23-06-2026-RETIE-libros-compilados.pdf
  - CREG 038/2014 (Codigo de Medida):
    https://gestornormativo.creg.gov.co/Publicac.nsf/1c09d18d2d5ffb5b05256eee00709c02/0131f0642192a5a205257cd800728c5e/$FILE/Creg038-2014.docx
  - CREG 015/2018 (NT1/NT2, remuneracion distribucion):
    https://gestornormativo.creg.gov.co/Publicac.nsf/1c09d18d2d5ffb5b05256eee00709c02/65f1aaf1d57726a90525822900064dac/$FILE/Creg015-2018.pdf
"""
import os
import sys
import glob
import time

from google import genai
from google.genai import types

STORE_DISPLAY_NAME = "retie-creg-normativa"


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: define GEMINI_API_KEY antes de correr este script.")
        sys.exit(1)

    paths = []
    for arg in sys.argv[1:]:
        matches = glob.glob(arg)
        if not matches:
            print(f"AVISO: '{arg}' no coincide con ningun archivo, se omite.")
        paths.extend(matches)
    if not paths:
        print(__doc__)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    existing_name = os.environ.get("RETIE_STORE_NAME")
    if existing_name:
        store = client.file_search_stores.get(name=existing_name)
        print(f"Reutilizando store existente: {store.name}")
    else:
        store = client.file_search_stores.create(
            config=types.CreateFileSearchStoreConfig(display_name=STORE_DISPLAY_NAME)
        )
        print(f"Store creado: {store.name}")

    for path in paths:
        fname = os.path.basename(path)
        print(f"Subiendo {fname} ...", end=" ", flush=True)
        op = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store.name,
            file=path,
            config=types.UploadToFileSearchStoreConfig(display_name=fname),
        )
        while not op.done:
            time.sleep(3)
            op = client.operations.get(op)
        if op.error:
            print(f"ERROR: {op.error}")
        else:
            print("OK")

    print()
    print("=" * 60)
    print(f"RETIE_STORE_NAME={store.name}")
    print("=" * 60)
    print("Copia ese valor a la variable de entorno RETIE_STORE_NAME del bot")
    print("(en Render: Settings > Environment del servicio) y reinicia el bot.")


if __name__ == "__main__":
    main()
