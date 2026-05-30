import io
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
