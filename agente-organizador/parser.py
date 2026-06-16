import io
import re
import unicodedata
from pathlib import Path

import pdfplumber
from pptx import Presentation


def clasificar_archivo(nombre: str, texto: str) -> str:
    nombre_normalizado = (nombre or "").lower()
    muestra_texto = (texto or "")[:300].lower()

    indicadores_nombre = [
        "outline",
        "index",
        "program",
        "syllabus",
        "c0",
        "tema0",
        "indice",
    ]
    indicadores_texto = [
        "outline",
        "contents",
        "index",
        "programa",
        "índice general",
        "tabla de contenidos",
    ]

    if any(indicador in nombre_normalizado for indicador in indicadores_nombre):
        return "contexto"
    if any(indicador in muestra_texto for indicador in indicadores_texto):
        return "contexto"

    return "teoria"


def extraer_texto(archivo_bytes, nombre_archivo) -> str:
    extension = Path(nombre_archivo).suffix.lower()

    if extension == ".pdf":
        texto_paginas = []
        with pdfplumber.open(io.BytesIO(archivo_bytes)) as pdf:
            for indice, pagina in enumerate(pdf.pages, start=1):
                texto = (pagina.extract_text() or "").strip()
                texto_paginas.append(f"--- Página {indice} ---\n{texto}")

        texto_final = "\n\n".join(texto_paginas).strip()
    elif extension == ".pptx":
        presentacion = Presentation(io.BytesIO(archivo_bytes))
        texto_slides = []

        for indice, slide in enumerate(presentacion.slides, start=1):
            fragmentos = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    texto_shape = (shape.text or "").strip()
                    if texto_shape:
                        fragmentos.append(texto_shape)

            texto_slide = "\n".join(fragmentos).strip()
            texto_slides.append(f"--- Slide {indice} ---\n{texto_slide}")

        texto_final = "\n\n".join(texto_slides).strip()
    else:
        raise ValueError(f"Formato no soportado para '{nombre_archivo}'. Solo se admite PDF o PPTX.")

    if not texto_final or len(texto_final) < 50:
        raise ValueError(
            f"No se pudo extraer texto suficiente de '{nombre_archivo}'. "
            "El archivo está vacío, protegido o no contiene texto legible."
        )

    return texto_final


# ---------------------------------------------------------------------------
# Detección determinista de subtemas por numeración jerárquica.
# Patrón replicado de agente-contenido/chunker.py (_NUMBERED_HEADER_RE).
# ---------------------------------------------------------------------------

_SUBTEMA_NUM_RE = re.compile(r"^\d+(?:\.\d+)*\.\s+\S")


def normalizar_subtema(texto: str) -> str:
    """Elimina prefijo numérico, acentos y puntuación; convierte a minúsculas.
    Usada para comparar candidatos entre fuentes (guía vs material).
    """
    s = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", (texto or "")).lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def extraer_subtemas_candidatos(texto: str) -> list[str]:
    """Detecta subtemas con numeración jerárquica ('3.2. Título').
    Devuelve nombres limpios (sin prefijo numérico), deduplicados por normalización.
    """
    candidatos: list[str] = []
    vistos: set[str] = set()
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not _SUBTEMA_NUM_RE.match(linea):
            continue
        nombre = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", linea).strip()
        if not nombre:
            continue
        clave = normalizar_subtema(nombre)
        if clave and clave not in vistos:
            candidatos.append(nombre)
            vistos.add(clave)
    return candidatos


def hay_discrepancia(lista_a: list[str], lista_b: list[str]) -> bool:
    """True si A y B no comparten ningún elemento (normalizado).
    Señal de revisión cuando la guía y el material describen el bloque de forma distinta.
    """
    if not lista_a or not lista_b:
        return False
    norm_a = {normalizar_subtema(x) for x in lista_a if x}
    norm_b = {normalizar_subtema(x) for x in lista_b if x}
    return norm_a.isdisjoint(norm_b)
