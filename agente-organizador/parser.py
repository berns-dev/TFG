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


# ---------------------------------------------------------------------------
# Filtro de calidad de subtemas candidatos.
#
# Causa raíz de dos fallos observados (Elementos de Máquinas, junio 2026):
#  1. Boilerplate administrativo de las guías docentes UniOvi tratado como
#     subtema técnico (Identificación, Contextualización, Requisitos,
#     Competencias, Metodología, Evaluación, Recursos/bibliografía). Estas
#     secciones se numeran en la guía y el regex de numeración las capturaba.
#  2. Fragmentos de texto corrido del material (p. ej. un paso de un ejemplo
#     resuelto "5.6. Además, de acuerdo a la tabla...") aceptados como subtema
#     porque empezaban por un número, sin validar que fueran un encabezado.
#
# Decisión de diseño documentada: un subtema candidato debe ser un encabezado
# real, no boilerplate administrativo ni prosa. Estos nombres administrativos
# son muy estables entre guías de la misma universidad, así que se filtran por
# patrón; la prosa se descarta por señales estructurales (conector inicial,
# ruido numérico, fragmento truncado).
# ---------------------------------------------------------------------------

# Secciones administrativas estándar de las guías docentes UniOvi. Prefijos
# (distintivos, no prefijan contenido técnico real) y nombres exactos cortos.
_GUIA_SECCIONES_ADMIN_PREFIJOS = (
    "identificacion de la asignatura",
    "competencias y resultados de aprendizaje",
    "metodologia y plan de trabajo",
    "evaluacion del aprendizaje",
    "recursos bibliografia",
    "distribucion de los contenidos",
)
_GUIA_SECCIONES_ADMIN_EXACTAS = {
    "contenidos", "contextualizacion", "requisitos", "competencias",
    "metodologia", "evaluacion", "recursos", "bibliografia",
    "presenciales", "no presenciales", "clases expositivas",
    "practicas de aula", "practicas de aula seminarios",
    "practicas de laboratorio", "practicas de laboratorio campo",
    "tutorias grupales", "sesiones de evaluacion",
    "trabajo autonomo", "trabajo en grupo",
    "exposicion de trabajos realizados en grupo",
    "evaluacion continua", "evaluacion extraordinaria", "evaluacion diferenciada",
}

# Conectores discursivos: una frase que empieza por uno de estos es prosa
# (texto corrido), nunca un título/encabezado de subtema.
_CONECTORES_PROSA = (
    "ademas", "asimismo", "por tanto", "por lo tanto", "sin embargo",
    "no obstante", "es decir", "de acuerdo", "por ejemplo", "en consecuencia",
    "por consiguiente", "entonces", "asi pues", "de hecho", "en este caso",
    "con ello", "con lo que", "de esta forma", "de esta manera", "de este modo",
    "por ultimo", "finalmente", "en resumen", "en definitiva", "a continuacion",
)

# Palabras-función con las que un encabezado real no termina; si una línea corta
# acaba en una de ellas es un fragmento truncado (típico de columnas de tabla).
_PALABRAS_FUNCION_FINAL = {
    "de", "del", "la", "el", "los", "las", "y", "o", "en", "a", "con",
    "por", "para", "que", "su", "sus", "un", "una", "al",
}


def _es_seccion_administrativa(norm: str) -> bool:
    """True si `norm` (nombre ya normalizado) es una sección administrativa de guía."""
    if norm in _GUIA_SECCIONES_ADMIN_EXACTAS:
        return True
    return any(norm.startswith(p) for p in _GUIA_SECCIONES_ADMIN_PREFIJOS)


def es_subtema_valido(nombre: str) -> bool:
    """True si `nombre` parece un subtema/encabezado técnico real.

    Filtro de calidad común a todos los caminos de detección. Rechaza:
      1. Secciones administrativas estándar de la guía docente UniOvi.
      2. Fragmentos de prosa que empiezan por un conector discursivo.
      3. Filas de datos numéricos (p. ej. filas de tablas de horas).
      4. Fragmentos cortos y truncados que terminan en palabra-función.
    """
    norm = normalizar_subtema(nombre)
    if not norm:
        return False
    if _es_seccion_administrativa(norm):
        return False
    if any(norm == c or norm.startswith(c + " ") for c in _CONECTORES_PROSA):
        return False
    tokens = norm.split()
    # Ruido numérico: 3+ tokens con dígitos → fila de tabla / fragmento de cálculo.
    n_num = sum(1 for t in tokens if any(ch.isdigit() for ch in t))
    if n_num >= 3:
        return False
    # Fragmento truncado: corto y acaba en palabra-función.
    if len(norm) <= 30 and tokens and tokens[-1] in _PALABRAS_FUNCION_FINAL:
        return False
    return True


def extraer_subtemas_candidatos(texto: str) -> list[str]:
    """Detecta subtemas con numeración jerárquica ('3.2. Título').
    Devuelve nombres limpios (sin prefijo numérico), deduplicados por normalización.
    Aplica el filtro de calidad es_subtema_valido() para descartar boilerplate
    administrativo y fragmentos de texto corrido.
    """
    candidatos: list[str] = []
    vistos: set[str] = set()
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not _SUBTEMA_NUM_RE.match(linea):
            continue
        nombre = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", linea).strip()
        if not nombre or not es_subtema_valido(nombre):
            continue
        clave = normalizar_subtema(nombre)
        if clave and clave not in vistos:
            candidatos.append(nombre)
            vistos.add(clave)
    return candidatos


def extraer_subtemas_guia(texto: str) -> list[str]:
    """Extrae los subtemas reales de la sección 'Contenidos' de una guía docente.

    Las guías UniOvi numeran TODAS sus secciones de primer nivel (1..8), de las
    cuales solo 'Contenidos' contiene temario real; el resto es boilerplate
    administrativo. Acotar la extracción a la sección 'Contenidos' excluye de
    raíz cabeceras, filas de tablas de horas y prosa de metodología/evaluación.

    Estrategia: localizar la cabecera 'N. Contenidos' y recoger los subtemas
    numerados hasta la siguiente cabecera de sección administrativa. Si no se
    encuentra 'Contenidos' (guía con otro formato), se degrada a
    extraer_subtemas_candidatos() sobre todo el texto. En ambos caminos se aplica
    el filtro de calidad es_subtema_valido().
    """
    lineas = [l.strip() for l in (texto or "").splitlines()]

    inicio = None
    for i, ln in enumerate(lineas):
        m = re.match(r"^\d+\.\s+(\S.*)$", ln)
        if m and normalizar_subtema(m.group(1)).startswith("contenidos"):
            inicio = i
            break

    if inicio is None:
        # Formato no reconocido: degradar a extracción genérica (ya filtrada).
        return extraer_subtemas_candidatos(texto)

    candidatos: list[str] = []
    vistos: set[str] = set()
    for ln in lineas[inicio + 1:]:
        if not _SUBTEMA_NUM_RE.match(ln):
            continue
        nombre = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", ln).strip()
        norm = normalizar_subtema(nombre)
        if not norm:
            continue
        # Fin de la sección 'Contenidos': siguiente cabecera administrativa.
        if _es_seccion_administrativa(norm):
            break
        if not es_subtema_valido(nombre) or norm in vistos:
            continue
        candidatos.append(nombre)
        vistos.add(norm)
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
        if not nombre or not es_subtema_valido(nombre):
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
            if not es_subtema_valido(item["titulo"]):
                continue
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


# ---------------------------------------------------------------------------
# Extracción de horas lectivas y nombre de descarga desde la guía docente.
#
# Lógica pura (solo re + unicodedata, sin Streamlit ni estado). Estas funciones
# son la fuente de verdad importable: tanto el app.py standalone como la
# app-unificada las consumen desde aquí en lugar de duplicarlas.
# ---------------------------------------------------------------------------


def extraer_horas_docencia(texto_guia: str) -> dict[str, int]:
    """
    Extrae horas TE/PA/PL de guías docentes heterogéneas (tablas o texto libre).
    Si no encuentra una categoría, devuelve 0 para esa categoría.
    """
    def norm(texto: str) -> str:
        base = unicodedata.normalize("NFKD", texto or "")
        base = base.encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"\s+", " ", base).strip()

    def parsear_numero(token: str) -> int | None:
        try:
            valor = float(token.replace(",", "."))
            if valor < 0:
                return None
            return int(round(valor))
        except ValueError:
            return None

    def categoria_fila_modalidad(linea_norm: str) -> str | None:
        # Reglas mutuamente excluyentes para evitar solapes TE/PA/PL.
        # Incluye raíz "pract" para abreviaturas tipo "Práct. de aula" (sin "practic").
        tiene_practica = ("practic" in linea_norm) or bool(re.search(r"\bpract\b", linea_norm))
        tiene_aula = "aula" in linea_norm
        tiene_seminario = "seminar" in linea_norm
        tiene_taller = "taller" in linea_norm
        tiene_laboratorio = "laborator" in linea_norm or re.search(r"\blab\b", linea_norm) is not None
        tiene_campo = "campo" in linea_norm
        tiene_informatica = "informatica" in linea_norm
        tiene_idiomas = "idioma" in linea_norm
        tiene_teoria = ("expositiv" in linea_norm) or ("teoric" in linea_norm) or ("magistral" in linea_norm)

        # PL primero: categoría más específica y fácil de confundir si no se prioriza.
        if tiene_laboratorio or (tiene_practica and (tiene_campo or tiene_informatica or tiene_idiomas)):
            return "laboratorio"
        # PA: solo con "práctica(s)" (no basta con "seminario"/"taller" sueltos: otras tablas
        # y el texto narrativo también los usan y pueden llevar a 14h en lugar de 7h).
        if tiene_practica and (tiene_aula or tiene_seminario or tiene_taller):
            return "aula"
        # TE: expositiva/teórica/magistral y sin prácticas.
        if tiene_teoria and not tiene_practica:
            return "teoria"
        return None

    def fuerza_fila_pa(linea_norm: str) -> int:
        """Mayor = más seguro que es la fila de modalidad PA (no otra tabla)."""
        if linea_norm is None:
            return 0
        tiene_practica = ("practic" in linea_norm) or bool(re.search(r"\bpract\b", linea_norm))
        if not tiene_practica:
            return 0
        if "laborator" in linea_norm or re.search(r"\blab\b", linea_norm) is not None:
            return 0
        tiene_aula = "aula" in linea_norm
        tiene_seminario = "seminar" in linea_norm
        tiene_taller = "taller" in linea_norm
        tiene_informatica = "informatica" in linea_norm
        tiene_idiomas = "idioma" in linea_norm
        tiene_campo = "campo" in linea_norm
        tiene_laboratorio = "laborator" in linea_norm or re.search(r"\blab\b", linea_norm) is not None
        if tiene_laboratorio or (tiene_practica and (tiene_campo or tiene_informatica or tiene_idiomas)):
            return 0
        if tiene_aula and not (tiene_informatica or tiene_idiomas):
            return 3
        if tiene_seminario or tiene_taller:
            return 2
        return 0

    def es_fila_desglose_temas(linea_norm: str) -> bool:
        """Evita filas de tablas por tema/unidad (suelen repetir columnas TE/PA/PL con otros totales)."""
        if re.match(r"^\d+\s*[\.\)]\s", linea_norm):
            return True
        if re.match(r"^tema\s*\d", linea_norm):
            return True
        if re.match(r"^unidad\s*\d", linea_norm):
            return True
        if re.match(r"^bloque\s*\d", linea_norm):
            return True
        return False

    def es_contexto_horario(linea_norm: str) -> bool:
        # Señales de que el número se refiere a carga horaria y no a conteos (sesiones, grupos...).
        return any(
            patron in linea_norm
            for patron in ("hora", "horas", "h ", " h", "lectiv", "dedicacion", "carga docente", "credit")
        )

    def linea_parece_header_tabla(linea_norm: str) -> bool:
        return (
            ("modalidad" in linea_norm or "modalidades" in linea_norm)
            and ("hora" in linea_norm or "horas" in linea_norm)
        )

    def extraer_hora_fila(linea_original: str) -> int | None:
        nums = [parsear_numero(m.group(0)) for m in re.finditer(r"\d+(?:[.,]\d+)?", linea_original)]
        nums = [n for n in nums if n is not None and 0 <= n <= 500]
        if not nums:
            return None
        candidatos = [n for n in nums if 0 <= n <= 120]
        return candidatos[0] if candidatos else nums[0]

    def es_linea_numerica_de_tabla(linea_original: str, linea_norm: str) -> bool:
        # Acepta líneas "continuación de fila" típicas del OCR de tablas, evita texto narrativo.
        if "sesion" in linea_norm or "sesiones" in linea_norm:
            return False
        numeros = re.findall(r"\d+(?:[.,]\d+)?", linea_original)
        if not numeros:
            return False
        letras = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", linea_original)
        # Heurística: línea casi numérica (poca letra) y al menos 1 número.
        return len(letras) <= 3

    lineas_originales = [l.strip() for l in (texto_guia or "").splitlines() if l.strip()]
    lineas_norm = [norm(l) for l in lineas_originales]

    def extraer_primera_hora_fila_tabla(linea_original: str) -> int | None:
        """
        En tablas MODALIDADES el orden suele ser Horas | % | Totales.
        No usar la posición del texto 'Horas' en la cabecera: cada fila tiene
        prefijo de longitud distinta y el número más cercano puede ser el %.
        """
        coincidencias = list(re.finditer(r"\d+(?:[.,]\d+)?", linea_original))
        for m in coincidencias:
            v = parsear_numero(m.group(0))
            if v is None:
                continue
            if 1900 <= v <= 2100:
                continue
            if 0 <= v <= 120:
                return v
        return None

    horas = {"teoria": 0, "aula": 0, "laboratorio": 0}

    # Estrategia 1 (preferente): detectar tabla(s) MODALIDADES y leer columna Horas.
    # Puede haber varias tablas (p. ej. desglose por temas + resumen); se elige la ventana
    # con más datos y mayor confianza en la fila PA.
    indices_headers = [i for i, ln in enumerate(lineas_norm) if linea_parece_header_tabla(ln)]
    mejor_ventana = None  # (puntuacion, indice_cabecera, dict horas)

    for idx_header in indices_headers:
        local = {"teoria": 0, "aula": 0, "laboratorio": 0}
        fuerza_pa_mejor = -1
        ventana_fin = min(len(lineas_originales), idx_header + 45)

        for i in range(idx_header + 1, ventana_fin):
            ln = lineas_norm[i]
            if es_fila_desglose_temas(ln):
                continue
            if "total" in ln and "modalidad" not in ln:
                continue

            categoria = categoria_fila_modalidad(ln)
            if categoria is None:
                continue

            if categoria == "aula":
                fuerza = fuerza_fila_pa(ln)
                if fuerza < fuerza_pa_mejor:
                    continue

            if categoria != "aula" and local[categoria] != 0:
                continue

            valor = extraer_primera_hora_fila_tabla(lineas_originales[i])

            if valor is None:
                for salto in (1, 2):
                    if i + salto >= ventana_fin:
                        break
                    ln_sig = lineas_norm[i + salto]
                    if es_fila_desglose_temas(ln_sig):
                        continue
                    if categoria_fila_modalidad(ln_sig) is not None or linea_parece_header_tabla(ln_sig):
                        break
                    if not es_linea_numerica_de_tabla(lineas_originales[i + salto], ln_sig):
                        continue
                    valor = extraer_primera_hora_fila_tabla(lineas_originales[i + salto])
                    if valor is not None:
                        break

            if valor is None:
                continue

            if categoria == "aula":
                fuerza = fuerza_fila_pa(ln)
                if fuerza < fuerza_pa_mejor:
                    continue
                local["aula"] = int(valor)
                fuerza_pa_mejor = fuerza
            else:
                local[categoria] = int(valor)

        completitud = sum(1 for v in local.values() if v > 0)
        puntuacion = completitud * 100 + fuerza_pa_mejor
        if mejor_ventana is None:
            mejor_ventana = (puntuacion, idx_header, local)
        elif puntuacion > mejor_ventana[0] or (
            puntuacion == mejor_ventana[0] and idx_header > mejor_ventana[1]
        ):
            # Empate: preferir tabla más abajo en el documento (suele ser el resumen MODALIDADES).
            mejor_ventana = (puntuacion, idx_header, local)

    if mejor_ventana is not None:
        horas = mejor_ventana[2]

    # Estrategia 2 (fallback): búsqueda en texto libre, siempre en la MISMA línea.
    # Se aplica tras tabla y exige señales horarias para evitar capturar "sesiones".
    if 0 in horas.values():
        for linea_original, linea_norm_item in zip(lineas_originales, lineas_norm):
            categoria = categoria_fila_modalidad(linea_norm_item)
            if categoria is None or horas[categoria] != 0:
                continue
            if not es_contexto_horario(linea_norm_item):
                # Evita confundir número de sesiones con horas.
                continue
            valor = extraer_hora_fila(linea_original)
            if valor is not None:
                horas[categoria] = int(valor)

    return {
        "horas_teoria": horas["teoria"],
        "horas_aula": horas["aula"],
        "horas_laboratorio": horas["laboratorio"],
    }


def construir_nombre_descarga(texto_guia: str) -> str:
    """Deriva un nombre de archivo de descarga a partir del nombre de la asignatura."""
    # Se busca el patrón habitual "NOMBRE ... CÓDIGO" para extraer la asignatura.
    coincidencia = re.search(r"NOMBRE\s+(.+?)\s+C[ÓO]DIGO", texto_guia or "", flags=re.IGNORECASE | re.DOTALL)
    if not coincidencia:
        return "Propuesta_asignatura.md"

    nombre_asignatura = coincidencia.group(1).strip()
    # Se eliminan caracteres no válidos para nombres de archivo.
    nombre_limpio = re.sub(r'[\\/:\*\?"<>\|]', "", nombre_asignatura)
    # Se normalizan espacios a guiones bajos.
    nombre_limpio = re.sub(r"\s+", "_", nombre_limpio).strip("_")
    if not nombre_limpio:
        return "Propuesta_asignatura.md"

    return f"Propuesta_{nombre_limpio}.md"


# ---------------------------------------------------------------------------
# Normalización de horas y conteo de bloques sobre el Markdown de organización.
# Lógica pura: transforman/leen el Markdown generado, sin tocar estado de UI.
# ---------------------------------------------------------------------------


def normalizar_horas_output(markdown: str, total_horas: float) -> tuple[str, dict | None]:
    """
    Verifica y normaliza la suma de horas de subtemas en el markdown generado.

    Si sum(horas_subtemas) != total_horas, redistribuye proporcionalmente (redondeo a
    0.5h) y actualiza también los encabezados ## Bloque N · Xh. Si la suma ya es
    correcta, devuelve el markdown sin modificar y None como diagnóstico.

    Returns:
        (markdown_corregido, info_ajuste) si se aplicó corrección
        (markdown, None) si la suma era exacta
    """
    if not total_horas or total_horas <= 0:
        return markdown, None

    FILA_RE = re.compile(r"^\| (.+?) \| ([\d]+(?:[.,]\d+)?)h? \| (.+?) \|\s*$")
    HDR_RE = re.compile(r"^(## Bloque \d+ — .+? · )([\d.]+)(h.*)$")
    _CABECERAS = {
        "subtema", "topic", "horas", "hours",
        "justificación", "justificacion", "justification",
        "origen", "origin",
    }

    lineas = markdown.splitlines(keepends=True)

    # -- Primera pasada: recoger (índice_línea, hora_original) de filas de datos --
    indices_filas: list[tuple[int, float]] = []
    for i, linea in enumerate(lineas):
        m = FILA_RE.match(linea.rstrip("\r\n"))
        if not m:
            continue
        col1 = m.group(1).strip().lower()
        col2_val = m.group(2).strip()
        if col1 in _CABECERAS or re.match(r"^-+$", col1) or re.match(r"^-+$", col2_val):
            continue
        try:
            indices_filas.append((i, float(col2_val.replace(",", "."))))
        except ValueError:
            pass

    if not indices_filas:
        return markdown, None

    horas_originales = [h for _, h in indices_filas]
    suma_actual = sum(horas_originales)

    if abs(suma_actual - total_horas) < 0.01:
        return markdown, None

    diferencia = suma_actual - total_horas

    # -- Escalar proporcionalmente a 0.5h --
    factor = total_horas / suma_actual
    horas_nuevas = [round(h * factor * 2) / 2 for h in horas_originales]
    # Compensar residuo de redondeo en el subtema con más horas
    residuo = total_horas - sum(horas_nuevas)
    if abs(residuo) >= 0.01:
        idx_max = horas_nuevas.index(max(horas_nuevas))
        horas_nuevas[idx_max] = round((horas_nuevas[idx_max] + residuo) * 2) / 2

    def fmt(v: float) -> str:
        return str(int(v)) if v == int(v) else f"{v:.1f}"

    # -- Segunda pasada: reconstruir líneas con nuevas horas de subtema --
    ajustes: dict[str, dict] = {}
    nuevas_lineas = list(lineas)

    for (idx_linea, h_antes), h_nueva in zip(indices_filas, horas_nuevas):
        linea_orig = lineas[idx_linea]
        m = FILA_RE.match(linea_orig.rstrip("\r\n"))
        if not m:
            continue
        if abs(h_antes - h_nueva) >= 0.05:
            nombre_sub = m.group(1).strip()
            ajustes[nombre_sub] = {"antes": h_antes, "despues": h_nueva}
        ending = linea_orig[len(linea_orig.rstrip("\r\n")):]
        nuevas_lineas[idx_linea] = f"| {m.group(1)} | {fmt(h_nueva)}h | {m.group(3)} |{ending}"

    # -- Actualizar encabezados de bloque con la suma de sus subtemas --
    indices_hdrs = [i for i, l in enumerate(nuevas_lineas) if HDR_RE.match(l.rstrip("\r\n"))]
    indices_hdrs.append(len(nuevas_lineas))  # sentinel

    for k in range(len(indices_hdrs) - 1):
        inicio_bloque = indices_hdrs[k]
        fin_bloque = indices_hdrs[k + 1]
        horas_bloque = [
            horas_nuevas[sub_idx]
            for sub_idx, (idx_linea, _) in enumerate(indices_filas)
            if inicio_bloque < idx_linea < fin_bloque
        ]
        if not horas_bloque:
            continue
        linea_hdr = nuevas_lineas[inicio_bloque]
        m = HDR_RE.match(linea_hdr.rstrip("\r\n"))
        if m:
            ending = linea_hdr[len(linea_hdr.rstrip("\r\n")):]
            nuevas_lineas[inicio_bloque] = m.group(1) + fmt(sum(horas_bloque)) + m.group(3) + ending

    return "".join(nuevas_lineas), {
        "diferencia": diferencia,
        "suma_antes": suma_actual,
        "ajustes": ajustes,
    }


def contar_bloques_output(markdown_text: str) -> int:
    """Cuenta encabezados ## Bloque N en el markdown generado.

    La regex es estricta: solo cuenta líneas que coinciden exactamente con
    el patrón de bloque temático (## Bloque <número>). Otros encabezados ##
    (subtítulos, secciones internas) no producen falsos positivos.
    """
    return len(re.findall(r"^## Bloque\s+\d+", markdown_text, re.MULTILINE))


# ---------------------------------------------------------------------------
# Parseo enriquecido del Markdown de organización para persistencia (BD).
#
# A diferencia de parsear_bloques_desde_markdown (orientado a la edición manual,
# devuelve solo nombre/horas/manual), esta función captura los metadatos que la
# app-unificada necesita para guardar en la base de datos: orden, evidencia,
# origen y la marca de fallback. La consume la app-unificada al confirmar la
# organización como definitiva.
# ---------------------------------------------------------------------------

# Cabeceras de tabla que no son filas de datos
_CABECERAS_TABLA = {
    "subtema", "topic", "horas", "hours",
    "justificación", "justificacion", "justification",
    "origen", "origin",
    "evidencia", "evidence",
}

# Contrato de formato del Agente Organizador (ver CLAUDE.md del monorepo):
#   ## Bloque N — NOMBRE · Xh
_HDR_BLOQUE_RE = re.compile(
    r"^##\s+Bloque\s+(\d+)\s+[—\-]+\s+(.+?)\s*[·•]\s*([\d.,]+)h",
    re.MULTILINE,
)
# Captura todas las celdas de una fila de tabla Markdown (separadas por '|').
_FILA_TABLA_COMPLETA_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)


def _parsear_celdas(linea: str) -> list[str]:
    """Extrae celdas de una línea de tabla Markdown como lista de strings limpios."""
    partes = linea.strip().strip("|").split("|")
    return [p.strip() for p in partes]


def parsear_bloques_organizador(markdown: str) -> list[dict]:
    """Extrae la lista de bloques y subtemas del output del Agente Organizador.

    Compatible con los formatos de tabla del Organizador:
      - 3 columnas: | Subtema | Horas | Origen |
      - 4 columnas: | Subtema | Horas | Evidencia | Origen |
      - antiguo 3 cols: | Subtema | Horas | Justificación |

    Returns:
        list[dict] con claves: numero (int), nombre (str), horas (float),
        subtemas (list[dict{nombre, horas, orden, evidencia, origen, es_fallback}])
    """
    bloques: list[dict] = []
    matches = list(_HDR_BLOQUE_RE.finditer(markdown))

    for i, m in enumerate(matches):
        numero = int(m.group(1))
        nombre = m.group(2).strip()
        horas_bloque = float(m.group(3).replace(",", "."))

        inicio = m.end()
        fin = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        seccion = markdown[inicio:fin]

        subtemas: list[dict] = []
        for fm in _FILA_TABLA_COMPLETA_RE.finditer(seccion):
            celdas = _parsear_celdas(fm.group(0))
            if len(celdas) < 2:
                continue
            col1 = celdas[0]
            col2 = celdas[1] if len(celdas) > 1 else ""
            # Saltar cabeceras, separadores y filas vacías.
            if col1.lower() in _CABECERAS_TABLA:
                continue
            if re.match(r"^-+$", col1) or re.match(r"^-+$", col2):
                continue
            if not col1:
                continue

            # Extraer horas del subtema (col2 puede tener "h" al final).
            horas_sub_raw = re.sub(r"[^\d.,]", "", col2)
            try:
                horas_sub = float(horas_sub_raw.replace(",", ".")) if horas_sub_raw else 0.0
            except ValueError:
                horas_sub = 0.0

            # Columnas opcionales: Evidencia (col3) y Origen (col4 ó col3).
            if len(celdas) >= 4:
                evidencia = celdas[2]
                origen = celdas[3]
            elif len(celdas) == 3:
                # Formato antiguo o 3-cols: tercera columna es Origen/Justificación.
                evidencia = ""
                origen = celdas[2]
            else:
                evidencia = ""
                origen = "Detectado"

            # Fallback: evidencia vacía o marcador explícito.
            _ev_norm = evidencia.strip().lower()
            es_fallback = int(
                _ev_norm in {"sin señal verificable", "sin senal verificable", "fallback", ""}
                and origen.strip().lower() in {"fallback", "sin señal", "sin senal", ""}
            )

            subtemas.append({
                "nombre": col1,
                "horas": horas_sub,
                "orden": len(subtemas) + 1,
                "evidencia": evidencia,
                "origen": origen,
                "es_fallback": es_fallback,
            })

        bloques.append({
            "numero": numero,
            "nombre": nombre,
            "horas": horas_bloque,
            "subtemas": subtemas,
        })

    return bloques
