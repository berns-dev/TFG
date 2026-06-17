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


# ---------------------------------------------------------------------------
# Extracción de señales estructurales con evidencia verificable.
# Objetivo: cada subbloque generado puede justificarse señalando una referencia
# concreta del documento fuente (número de sección, slide, página).
# ---------------------------------------------------------------------------


def extraer_titulos_slides_pptx(archivo_bytes: bytes) -> list[dict]:
    """Extrae títulos de diapositiva de un PPTX como señales estructurales.

    Prioridad por shape:
    1. Placeholder con idx=0 (marcador oficial de título en la plantilla).
    2. Primer texto corto sin saltos de línea (≤ 100 caracteres) — heurística
       para slides sin placeholder de título explícito.

    Los títulos duplicados (por normalización) se descartan para no generar
    candidatos repetidos cuando varias slides comparten encabezado.

    Retorna [{slide, titulo, referencia}].
    """
    presentacion = Presentation(io.BytesIO(archivo_bytes))
    resultados: list[dict] = []
    vistos: set[str] = set()

    for indice, slide in enumerate(presentacion.slides, start=1):
        titulo_oficial: str | None = None
        primer_texto_corto: str | None = None

        for shape in slide.shapes:
            if not hasattr(shape, "text"):
                continue
            texto = (shape.text or "").strip()
            if not texto:
                continue

            ph = getattr(shape, "placeholder_format", None)
            if ph is not None and ph.idx == 0:
                titulo_oficial = texto
                break

            if primer_texto_corto is None and len(texto) <= 100 and "\n" not in texto:
                primer_texto_corto = texto

        titulo_final = titulo_oficial or primer_texto_corto
        if not titulo_final:
            continue

        clave = normalizar_subtema(titulo_final)
        if not clave or clave in vistos:
            continue
        vistos.add(clave)

        resultados.append({
            "slide": indice,
            "titulo": titulo_final,
            "referencia": f"Slide {indice}",
        })

    return resultados


def extraer_candidatos_con_evidencia(
    texto: str,
    nombre_archivo: str = "",
    archivo_bytes: bytes | None = None,
) -> list[dict]:
    """Detecta subbloques con referencia estructural verificable.

    Prioridad de fuentes (estricta — si la primera produce resultados, no se
    consulta la siguiente):

    1. Secciones numeradas en el texto extraído (e.g. '3.2. Título').
       Aplica a PDF y PPTX. Evidencia: 'Sección 3.2'.
    2. Títulos de diapositiva en PPTX (placeholder idx=0 o heurística).
       Solo si no se encontraron secciones numeradas. Evidencia: 'Slide N'.

    Retorna [] si ninguna fuente ofrece señales verificables — el bloque debe
    tratarse como un único subbloque (fallback); el caller es responsable de
    marcarlo en la interfaz.

    Cada ítem: {nombre: str, evidencia: str, fuente: str}
      - fuente: 'numeracion' | 'titulo_slide'
    """
    candidatos: list[dict] = []
    vistos: set[str] = set()

    # Estrategia 1 — secciones numeradas
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not _SUBTEMA_NUM_RE.match(linea):
            continue
        m_pref = re.match(r"^(\d+(?:\.\d+)*\.)\s*", linea)
        prefijo = m_pref.group(1).rstrip(".") if m_pref else ""
        nombre = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", linea).strip()
        if not nombre:
            continue
        clave = normalizar_subtema(nombre)
        if not clave or clave in vistos:
            continue
        evidencia = f"Sección {prefijo}" if prefijo else "Sección numerada"
        candidatos.append({"nombre": nombre, "evidencia": evidencia, "fuente": "numeracion"})
        vistos.add(clave)

    if candidatos:
        return candidatos

    # Estrategia 2 — títulos de diapositiva PPTX
    ext = Path(nombre_archivo).suffix.lower() if nombre_archivo else ""
    if ext == ".pptx" and archivo_bytes is not None:
        for item in extraer_titulos_slides_pptx(archivo_bytes):
            clave = normalizar_subtema(item["titulo"])
            if not clave or clave in vistos:
                continue
            candidatos.append({
                "nombre": item["titulo"],
                "evidencia": item["referencia"],
                "fuente": "titulo_slide",
            })
            vistos.add(clave)

    return candidatos  # lista vacía → fallback obligatorio


# ---------------------------------------------------------------------------
# Serialización / deserialización de la organización para edición manual.
# ---------------------------------------------------------------------------


def parsear_bloques_desde_markdown(markdown: str) -> list[dict]:
    """Parsea el Markdown de organización en una lista de bloques estructurados.

    Retorna [{numero, nombre, horas, subtemas: [{nombre, horas, manual}], manual}].
    Retorna [] si no se encuentran encabezados ## Bloque N.

    Tolerante a los dos formatos de tabla (3 columnas con Justificación/Origen,
    4 columnas con Evidencia+Origen). Solo extrae nombre y horas de cada subtema;
    el resto de metadatos no se necesita para la edición manual.
    """
    BLOQUE_RE = re.compile(r"^## Bloque (\d+) — (.+?) · ([\d.]+)h", re.MULTILINE)
    FILA_RE = re.compile(r"^\| (.+?) \| ([\d]+(?:[.,]\d+)?)h? \|")
    _EXCLUIR = {
        "subtema", "topic", "horas", "hours",
        "justificación", "justificacion", "justification",
        "evidencia", "evidence", "origen", "origin",
    }

    bloques: list[dict] = []
    matches = list(BLOQUE_RE.finditer(markdown))

    for i, m in enumerate(matches):
        numero = int(m.group(1))
        nombre = m.group(2).strip()
        horas = float(m.group(3))
        inicio = m.end()
        fin = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        seccion = markdown[inicio:fin]

        subtemas: list[dict] = []
        for linea in seccion.splitlines():
            fm = FILA_RE.match(linea.strip())
            if not fm:
                continue
            col1 = fm.group(1).strip()
            if col1.lower() in _EXCLUIR or re.match(r"^-+$", col1.replace(" ", "")):
                continue
            try:
                h = float(fm.group(2).replace(",", "."))
            except ValueError:
                continue
            subtemas.append({"nombre": col1, "horas": h, "manual": False})

        bloques.append({
            "numero": numero,
            "nombre": nombre,
            "horas": horas,
            "subtemas": subtemas,
            "manual": False,
        })

    return bloques


def regenerar_markdown_desde_bloques(
    bloques: list[dict],
    markdown_original: str,
) -> str:
    """Regenera el Markdown de organización a partir del estado estructurado.

    Preserva la cabecera (título + resumen de horas) y el pie (nota PL) del
    markdown original para no perder metadatos de la asignatura. Las horas
    de cada bloque se recalculan como suma de sus subtemas.

    Formato de salida: | Subtema | Horas | Origen | (3 columnas).
    El origen es 'Manual' para subtemas añadidos a mano, 'Detectado' para el resto.
    """
    BLOQUE_RE = re.compile(r"^## Bloque \d+", re.MULTILINE)
    FOOTER_RE = re.compile(r"^> ", re.MULTILINE)

    primer_m = BLOQUE_RE.search(markdown_original)
    header = markdown_original[: primer_m.start()].rstrip() if primer_m else ""

    footer_matches = list(FOOTER_RE.finditer(markdown_original))
    if footer_matches:
        linea_inicio = markdown_original.rfind("\n", 0, footer_matches[-1].start()) + 1
        footer = markdown_original[linea_inicio:].strip()
    else:
        footer = ""

    def fmt_h(v: float) -> str:
        return str(int(v)) if v == int(v) else f"{v:.1f}"

    partes: list[str] = []
    if header:
        partes.append(header + "\n\n---\n")

    for bloque in bloques:
        horas_b = (
            sum(s["horas"] for s in bloque["subtemas"])
            if bloque["subtemas"]
            else bloque["horas"]
        )
        partes.append(
            f"\n## Bloque {bloque['numero']} — {bloque['nombre']} · {fmt_h(horas_b)}h\n\n"
        )
        partes.append("| Subtema | Horas | Origen |\n")
        partes.append("|---------|-------|--------|\n")
        for sub in bloque["subtemas"]:
            origen = "Manual" if sub.get("manual") else "Detectado"
            partes.append(f"| {sub['nombre']} | {fmt_h(sub['horas'])}h | {origen} |\n")
        partes.append("\n")

    partes.append("---\n")
    if footer:
        partes.append(f"\n{footer}\n")

    return "".join(partes)
