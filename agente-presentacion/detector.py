"""Deteccion de secciones con contenido matematico en Markdown.

Pipeline:
  1. Detectar elementos matematicos individuales (regex):
     - Bloques LaTeX $$...$$
     - Inline $...$ (filtros de trivialidad + es_constante_pura)
     - Tablas Markdown con contenido numerico
  2. Agrupar por seccion (## / ###) — un elemento por seccion con contenido.
  3. Filtrar con Haiku (PROMPT_DETECTOR_INTERACTIVIDAD): solo INTERACTIVO=true
     y CONFIANZA ALTA o MEDIA. Las tablas omiten este filtro. Fail-open ante
     error de API (decisión de diseño: no bloquear al profesor).
  4. Evaluar advertencia (razonador Sonnet) solo si analizar_advertencias=True
     (opt-in en la UI; consume más créditos).

Criterios actuales de deteccion regex (fase 1):
  - Bloque $$...$$: cualquier expresion no vacia que no sea constante pura.
  - Inline $...$: longitud >= MIN_LATEX_CHARS; descarta digitos sueltos,
    letra aislada, unidades puras; descarta constantes puras (es_constante_pura).
  - Tabla: >= 40 % celdas numericas.
  - Clasificacion tipo: "relacion" si hay '=' y >= MIN_VARIABLES_FOR_RELACION
    variables distintas; "ecuacion" en otro caso; "tabla" para tablas.
  - Agrupacion: todas las expresiones de una seccion se fusionan; el nombre
    es el encabezado ### mas cercano.

Falsos positivos conocidos en Tema_3_curado.md (regex sin filtro Haiku):
  - "Densidad de dislocaciones": $$10^8 \\text{ cm...}$$ — constante empirica.
  - "Endurecimiento por deformacion plastica": $10^{11}$ — constante empirica.
  - "Discrepancia entre teoria y experimentacion": $E/1000$ — ratio fijo.
  - "Comportamiento elastico del vidrio...": cadena de derivaciones algebraicas
    (sigma, W, gamma) sin relacion nueva explorable para el alumno.
  - "Concentracion de tensiones", "Relacion con la tension teorica": contexto
    cualitativo o sustituciones sin variables manipulables nuevas.
  - "Temperatura y velocidad de carga": comparaciones $T_1$, $T_2$ puntuales.

Cada elemento devuelto tiene:
    id, tipo, nombre, expresion, contexto, seccion, es_bloque, advertencia.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    CONTEXTO_CHARS,
    MIN_LATEX_CHARS,
    MIN_VARIABLES_FOR_RELACION,
    MODEL_FAST,
    MODEL_SMART,
    REQUEST_TIMEOUT_SECONDS,
)
from prompts import (
    PROMPT_DETECTOR_INTERACTIVIDAD,
    PROMPT_RAZONADOR_VISUALIZACION,
    build_detector_message,
    build_razonador_message,
)

_MAX_ADVERTENCIA_WORKERS = 4
_MAX_HAIKU_WORKERS = 4

_PATRONES_VALIDOS = frozenset({
    "CURVA_SIMPLE",
    "FAMILIA_CURVAS",
    "REGION_CRITERIO",
    "MAPA_2D",
    "TRAYECTORIA",
    "RESPUESTA_FRECUENCIAL",
    "ANIMACION_MECANISMO",
})

# ---------------------------------------------------------------------------
# Patrones de deteccion
# ---------------------------------------------------------------------------

# Bloques $$...$$ (no greedy, multilinea)
_BLOCK_LATEX_RE = re.compile(r"\$\$([\s\S]+?)\$\$")

# Inline $...$ — no casa con $$ (negative lookbehind/lookahead)
_INLINE_LATEX_RE = re.compile(r"(?<!\$)\$([^$\n]+?)\$(?!\$)")

# Tabla Markdown: linea cabecera | sep | filas
_TABLE_RE = re.compile(
    r"(\|[^\n]+\|\n\|[-|: ]+\|\n(?:\|[^\n]+\|\n?)+)",
    re.MULTILINE,
)

# Encabezados H1/H2/H3
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# Variables matematicas: letras griegas LaTeX y letras latinas sueltas
_VARIABLE_RE = re.compile(
    r"\\(?:alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta"
    r"|iota|kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|varsigma|tau"
    r"|upsilon|phi|varphi|chi|psi|omega"
    r"|Alpha|Beta|Gamma|Delta|Epsilon|Zeta|Eta|Theta|Iota|Kappa|Lambda|Mu"
    r"|Nu|Xi|Pi|Rho|Sigma|Tau|Upsilon|Phi|Chi|Psi|Omega)"
    r"|(?<![\\a-zA-Z])[a-zA-Z](?:_\{[^}]+\}|_[a-zA-Z0-9])?(?![a-zA-Z])"
)

# Celda numerica: numero con punto o coma decimal, posible signo y unidades
_NUMERIC_CELL_RE = re.compile(
    r"^[−\-]?[\d]+(?:[.,][\d]+)?(?:\s*[a-zA-ZμΩ°%×·]+)?$"
)

_CONTEXT_CAP = 3000  # caracteres maximos del contexto de seccion


# ---------------------------------------------------------------------------
# Helpers — deteccion individual
# ---------------------------------------------------------------------------

def _find_nearest_heading(text: str, pos: int) -> str:
    """Return the text of the nearest heading above `pos`."""
    headings = [
        (m.start(), m.group(2).strip())
        for m in _HEADING_RE.finditer(text)
    ]
    above = [(p, h) for p, h in headings if p < pos]
    return above[-1][1] if above else ""


def _count_distinct_variables(expr: str) -> int:
    """Count distinct mathematical variables in a LaTeX expression."""
    return len(set(_VARIABLE_RE.findall(expr)))


def _classify_latex(expr: str) -> str:
    """Classify a LaTeX expression as 'ecuacion' or 'relacion'."""
    has_equals = (
        "=" in expr
        and "\\neq" not in expr
        and "\\leq" not in expr
        and "\\geq" not in expr
    )
    n_vars = _count_distinct_variables(expr)
    if has_equals and n_vars >= MIN_VARIABLES_FOR_RELACION:
        return "relacion"
    return "ecuacion"


def es_constante_pura(expresion: str) -> bool:
    """True si la expresion LaTeX es un valor numerico fijo sin variables explorables.

    Ejemplos True: 10^8, 10^{11}, E/1000, E/10
    Ejemplos False: sigma_y = sigma_0 + k_y/sqrt(d), F/A * cos^2 theta
    """
    expr = re.sub(r"^\$\$?|\$\$?$", "", expresion.strip())
    expr_compact = re.sub(r"\s+", "", expr)

    if re.match(
        r"^[A-Z](?:_\{[^}]+\}|_[a-zA-Z0-9])?\s*[/\*]\s*\d+(?:\.\d+)?$",
        expr_compact,
    ):
        return True
    if re.match(r"^[A-Z]/\d+$", expr_compact):
        return True

    if _count_distinct_variables(expr) >= 1:
        return False

    unidades = r"cm|mm|μm|um|MPa|GPa|nm|kg|N|Pa|J|m|s|Hz"
    expr_limpia = re.sub(r"\\text\{[^}]*\}", "", expr)
    expr_limpia = re.sub(r"\\(?:mathrm|mathbf)\{[^}]*\}", "", expr_limpia)
    expr_limpia = re.sub(r"\s+", "", expr_limpia)

    if re.match(rf"^[\d\^\{{\}}\+\-\*\/\.\,\\]+(?:{unidades})?$", expr_limpia, re.I):
        return True
    if re.match(r"^[\d\^\{\}\.\,]+$", expr_limpia):
        return True

    expr_ratio = re.sub(r"[^A-Za-z0-9/*]", "", expr_limpia)
    return bool(re.match(r"^[A-Z]/\d+$", expr_ratio))


def _parse_detector_response(raw: str) -> dict[str, Any]:
    """Parsea la respuesta XML de Haiku para el detector."""
    interactivo_raw = (_extract_xml_tag(raw, "INTERACTIVO") or "").lower()
    interactivo = interactivo_raw in ("true", "si", "sí", "yes", "1")
    confianza = (_extract_xml_tag(raw, "CONFIANZA") or "BAJA").upper()
    if confianza not in ("ALTA", "MEDIA", "BAJA"):
        confianza = "BAJA"
    return {
        "interactivo": interactivo,
        "confianza": confianza,
        "tipo": _extract_xml_tag(raw, "TIPO") or "ninguno",
        "nombre": _extract_xml_tag(raw, "NOMBRE") or "",
        "variables": _extract_xml_tag(raw, "VARIABLES") or "ninguna",
    }


def _evaluar_interactividad_haiku(elemento: dict[str, Any]) -> bool:
    """True si Haiku clasifica el elemento como interactivo con confianza ALTA/MEDIA.

    Fail-open: ante error de API o parseo devuelve True para no bloquear al profesor.
    Es una decisión de diseño explícita — la detección regex previa ya filtró candidatos.
    """
    if not ANTHROPIC_API_KEY:
        return True

    fragmento = (
        f"SECCION: {elemento.get('nombre', '')}\n\n"
        f"EXPRESIONES:\n{elemento.get('expresion', '')}\n\n"
        f"CONTEXTO:\n{elemento.get('contexto', '')}"
    )
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=float(REQUEST_TIMEOUT_SECONDS),
    )
    try:
        response = client.messages.create(
            model=MODEL_FAST,
            max_tokens=256,
            system=PROMPT_DETECTOR_INTERACTIVIDAD,
            messages=[{"role": "user", "content": build_detector_message(fragmento)}],
        )
        raw = response.content[0].text.strip()
        parsed = _parse_detector_response(raw)
        return (
            parsed["interactivo"]
            and parsed["confianza"] in ("ALTA", "MEDIA")
        )
    except Exception:  # noqa: BLE001
        return True


def _is_table_numeric(table_md: str) -> bool:
    """Return True if the table contains mostly numeric data cells."""
    lines = table_md.strip().split("\n")
    data_lines = [
        ln for ln in lines[2:]
        if ln.strip() and not re.match(r"^\|[-| :]+\|", ln.strip())
    ]
    if not data_lines:
        return False

    numeric = 0
    total = 0
    for line in data_lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        for cell in cells:
            if not cell:
                continue
            total += 1
            if _NUMERIC_CELL_RE.match(cell):
                numeric += 1

    return total > 0 and (numeric / total) >= 0.4


# ---------------------------------------------------------------------------
# Helpers — agrupacion por seccion
# ---------------------------------------------------------------------------

def _extraer_textos_secciones(text: str) -> dict[str, str]:
    """Return {heading_text: section_body_text} for each heading in the document.

    Sections are defined as the text from the end of a heading line to the
    start of the next heading (or end of document). Text before the first
    heading is stored under the empty-string key.

    If the same heading appears more than once, only the first occurrence is
    kept to avoid key collisions (edge case in real documents).

    Args:
        text: Full markdown document.

    Returns:
        Ordered dict mapping each section heading to its body text.
    """
    headings = list(_HEADING_RE.finditer(text))
    result: dict[str, str] = {}

    # Preamble: text before the first heading
    if headings:
        preamble = text[: headings[0].start()].strip()
        if preamble:
            result[""] = preamble
    else:
        # No headings at all — entire document is preamble
        result[""] = text.strip()
        return result

    for i, m in enumerate(headings):
        heading_text = m.group(2).strip()
        body_start = m.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[body_start:body_end].strip()
        if heading_text not in result:  # keep first occurrence
            result[heading_text] = body

    return result


def _format_section_expresion(items: list[dict]) -> str:
    """Format all individual expressions in a section into a single string.

    Block LaTeX is wrapped in $$...$$, inline in $...$, tables kept as-is.
    Expressions are joined with a blank line so Sonnet and Streamlit's
    markdown renderer both see them as separate blocks.

    Args:
        items: Individual element dicts from the raw detection step.

    Returns:
        Multi-expression string (e.g. "$$F = ma$$\\n\\n$$E = mc^2$$").
    """
    parts: list[str] = []
    for it in items:
        if it["tipo"] == "tabla":
            parts.append(it["expresion"])
        elif it.get("es_bloque"):
            parts.append(f"$$\n{it['expresion']}\n$$")
        else:
            parts.append(f"${it['expresion']}$")
    return "\n\n".join(parts)


def _nombre_sin_seccion(items: list[dict]) -> str:
    """Fallback name when equations appear before any heading.

    Uses the first 6 tokens of the first item's context.

    Args:
        items: List of raw items with no associated section heading.

    Returns:
        Short descriptive string (e.g. "El esfuerzo axial viene dado").
    """
    ctx = items[0].get("contexto", "") if items else ""
    words = ctx.split()[:6]
    return " ".join(words) if words else "Introducción"


# ---------------------------------------------------------------------------
# Valor pedagógico (razonador Sonnet, opt-in desde la UI)
# ---------------------------------------------------------------------------

def _extract_xml_tag(raw: str, tag: str) -> str | None:
    """Extrae el contenido entre <TAG> y </TAG>, tolerando espacios y saltos."""
    match = re.search(
        rf"<{tag}>\s*(.*?)\s*</{tag}>",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _fallback_visualizacion(
    elemento: dict,
    patron_invalido: str | None = None,
) -> dict:
    """Dict de visualización por defecto cuando el parsing falla."""
    variables_entrada: list[dict] = elemento.get("variables_entrada", [])
    variable_salida: dict = elemento.get(
        "variable_salida", {"nombre": "Y", "unidades": ""}
    )
    params = ", ".join(
        v.get("nombre", "") for v in variables_entrada if v.get("nombre")
    )
    eje_x = (
        variables_entrada[0].get("nombre", "X")
        if variables_entrada
        else "X"
    )
    justificacion = (
        f"Fallback: patrón '{patron_invalido}' no reconocido."
        if patron_invalido
        else "Fallback: no se pudo parsear la respuesta del razonador."
    )
    return {
        "VISUALIZABLE": "SI",
        "PATRON": "CURVA_SIMPLE",
        "EJE_X": eje_x,
        "EJE_Y": variable_salida.get("nombre", "Y"),
        "PARAMETROS_SLIDER": params,
        "PARAMETRO_FAMILIA": "",
        "SLIDERS_DESCARTADOS": "",
        "ESCALA_LOG_X": "NO",
        "ESCALA_LOG_Y": "NO",
        "JUSTIFICACION": justificacion,
        "RANGO_VARIABLES": "",
        "ZONA_VALIDEZ": "",
    }


def _parse_visualizacion(raw: str, elemento: dict) -> dict:
    """Parsea la respuesta XML del razonador (visualizable o patrón)."""
    visualizable = _extract_xml_tag(raw, "VISUALIZABLE")
    if visualizable and visualizable.upper() == "NO":
        return {
            "VISUALIZABLE": "NO",
            "RAZON": _extract_xml_tag(raw, "RAZON") or "Sin valor pedagógico interactivo.",
        }

    patron = _extract_xml_tag(raw, "PATRON")
    if not patron or patron not in _PATRONES_VALIDOS:
        return _fallback_visualizacion(elemento, patron)

    return {
        "VISUALIZABLE": "SI",
        "PATRON": patron,
        "EJE_X": _extract_xml_tag(raw, "EJE_X") or "",
        "EJE_Y": _extract_xml_tag(raw, "EJE_Y") or "",
        "PARAMETROS_SLIDER": _extract_xml_tag(raw, "PARAMETROS_SLIDER") or "",
        "PARAMETRO_FAMILIA": _extract_xml_tag(raw, "PARAMETRO_FAMILIA") or "",
        "SLIDERS_DESCARTADOS": _extract_xml_tag(raw, "SLIDERS_DESCARTADOS") or "",
        "ESCALA_LOG_X": _extract_xml_tag(raw, "ESCALA_LOG_X") or "NO",
        "ESCALA_LOG_Y": _extract_xml_tag(raw, "ESCALA_LOG_Y") or "NO",
        "JUSTIFICACION": _extract_xml_tag(raw, "JUSTIFICACION") or "",
        "RANGO_VARIABLES": _extract_xml_tag(raw, "RANGO_VARIABLES") or "",
        "ZONA_VALIDEZ": _extract_xml_tag(raw, "ZONA_VALIDEZ") or "",
    }


def _razonar_visualizacion(
    elemento: dict,
    client: anthropic.Anthropic,
    verbose: bool = False,
    texto_original: str | None = None,
) -> dict:
    """Llama al razonador Sonnet y devuelve el dict de visualización parseado."""
    user_msg = build_razonador_message(elemento, texto_original)

    response = client.messages.create(
        model=MODEL_SMART,
        max_tokens=1024,
        system=PROMPT_RAZONADOR_VISUALIZACION,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text.strip()
    return _parse_visualizacion(raw, elemento)


def evaluar_advertencia(elemento: dict) -> str | None:
    """Evalúa valor pedagógico en detección; retorna RAZON o None.

    Usado por detectar_elementos() para rellenar el campo ``advertencia`` del
    elemento antes de mostrarlo al profesor. No descarta ni genera HTML.
    """
    if not ANTHROPIC_API_KEY:
        return None

    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=float(REQUEST_TIMEOUT_SECONDS),
    )
    try:
        visualizacion = _razonar_visualizacion(elemento, client, verbose=False)
    except Exception:  # noqa: BLE001
        return None

    if visualizacion.get("VISUALIZABLE") == "NO":
        return visualizacion.get("RAZON") or "Sin valor pedagógico interactivo."
    return None


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def detectar_elementos(
    markdown_text: str,
    *,
    analizar_advertencias: bool = False,
) -> list[dict[str, Any]]:
    """Detect sections with mathematical content in a markdown document.

    Returns one element per section that contains at least one equation,
    parametric relation, or numeric table. The element name is the section
    heading. Individual equations within a section are combined into a single
    expresion field.

    This granularity (one element per section) is intentional: it produces a
    manageable number of checkboxes (one per topic) instead of one per
    equation, and gives the HTML generator enough context to build a coherent
    interactive block per section.

    Args:
        markdown_text: Full markdown content (typically from Agente Contenido).
        analizar_advertencias: Si True, llama a Sonnet por elemento para rellenar
            el campo ``advertencia`` (consume más créditos API).

    Returns:
        List of element dicts in document order. Each dict has:
        id, tipo, nombre, expresion, contexto, seccion, es_bloque.
    """
    # ── Phase 1: collect all individual raw items ──────────────────────────
    raw_items: list[dict[str, Any]] = []
    seen_positions: set[int] = set()

    # Block LaTeX: $$...$$
    for match in _BLOCK_LATEX_RE.finditer(markdown_text):
        if match.start() in seen_positions:
            continue
        for p in range(match.start(), match.end()):
            seen_positions.add(p)

        expr = match.group(1).strip()
        if not expr or es_constante_pura(expr):
            continue

        pre_start = max(0, match.start() - CONTEXTO_CHARS)
        post_end = min(len(markdown_text), match.end() + CONTEXTO_CHARS)
        ctx = markdown_text[pre_start:match.start()].strip()[-120:] + " … " + \
              markdown_text[match.end():post_end].strip()[:120]

        raw_items.append({
            "tipo": _classify_latex(expr),
            "expresion": expr,
            "contexto": ctx,
            "seccion": _find_nearest_heading(markdown_text, match.start()),
            "es_bloque": True,
            "_pos": match.start(),
        })

    # Inline LaTeX: $...$
    for match in _INLINE_LATEX_RE.finditer(markdown_text):
        if match.start() in seen_positions:
            continue

        expr = match.group(1).strip()

        # Trivial expression filters
        if len(expr) < MIN_LATEX_CHARS:
            continue
        if re.match(r"^[\d\s.,±]+$", expr):
            continue
        if re.match(r"^[a-zA-Z]$", expr):
            continue
        if re.match(r"^[\d.]+\s*(?:/\s*[\d.]+)?\s*[a-zA-Z²³]+$", expr):
            continue
        if es_constante_pura(expr):
            continue

        for p in range(match.start(), match.end()):
            seen_positions.add(p)

        pre_start = max(0, match.start() - CONTEXTO_CHARS)
        post_end = min(len(markdown_text), match.end() + CONTEXTO_CHARS)
        ctx = markdown_text[pre_start:match.start()].strip()[-120:] + " … " + \
              markdown_text[match.end():post_end].strip()[:120]

        raw_items.append({
            "tipo": _classify_latex(expr),
            "expresion": expr,
            "contexto": ctx,
            "seccion": _find_nearest_heading(markdown_text, match.start()),
            "es_bloque": False,
            "_pos": match.start(),
        })

    # Markdown tables with numeric data
    for match in _TABLE_RE.finditer(markdown_text):
        if match.start() in seen_positions:
            continue

        table_md = match.group(0)
        if not _is_table_numeric(table_md):
            continue

        for p in range(match.start(), match.end()):
            seen_positions.add(p)

        pre_start = max(0, match.start() - CONTEXTO_CHARS)
        post_end = min(len(markdown_text), match.end() + CONTEXTO_CHARS)
        ctx = markdown_text[pre_start:match.start()].strip()[-120:] + " … " + \
              markdown_text[match.end():post_end].strip()[:120]

        raw_items.append({
            "tipo": "tabla",
            "expresion": table_md.strip(),
            "contexto": ctx,
            "seccion": _find_nearest_heading(markdown_text, match.start()),
            "es_bloque": True,
            "_pos": match.start(),
        })

    if not raw_items:
        return []

    # Sort by document order
    raw_items.sort(key=lambda e: e["_pos"])

    # ── Phase 2: extract full section texts for rich context ───────────────
    section_texts = _extraer_textos_secciones(markdown_text)

    # ── Phase 3: group by section (preserves document order, Python 3.7+) ──
    by_section: dict[str, list[dict]] = {}
    for item in raw_items:
        sec = item.get("seccion", "")
        if sec not in by_section:
            by_section[sec] = []
        by_section[sec].append(item)

    # ── Phase 4: one element per section ──────────────────────────────────
    elementos: list[dict[str, Any]] = []
    for i, (seccion, items) in enumerate(by_section.items()):
        # Dominant type: prefer "relacion", then "ecuacion", "tabla" only if all are tables
        tipos = [it["tipo"] for it in items]
        if "relacion" in tipos:
            tipo = "relacion"
        elif all(t == "tabla" for t in tipos):
            tipo = "tabla"
        else:
            tipo = "ecuacion"

        # Name: section heading, or first-context fallback
        nombre = seccion if seccion else _nombre_sin_seccion(items)

        # Expression: all expressions in the section formatted together
        expresion = _format_section_expresion(items)

        # Context: full section text (rich context for Sonnet), capped
        contexto_seccion = section_texts.get(seccion, "")
        if not contexto_seccion:
            # Fallback: combine individual context snippets
            contexto_seccion = " … ".join(
                it.get("contexto", "") for it in items[:3]
            )
        contexto = contexto_seccion[:_CONTEXT_CAP]

        elementos.append({
            "id": i,
            "tipo": tipo,
            "nombre": nombre,
            "expresion": expresion,
            "contexto": contexto,
            "seccion": seccion,
            "es_bloque": True,
            "advertencia": None,
        })

    # ── Phase 5: filtro Haiku (interactividad + confianza) ─────────────────
    if elementos:
        candidatos = [el for el in elementos if el["tipo"] != "tabla"]
        tablas = [el for el in elementos if el["tipo"] == "tabla"]
        aprobados: list[dict[str, Any]] = list(tablas)

        if candidatos:
            workers = min(len(candidatos), _MAX_HAIKU_WORKERS)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_evaluar_interactividad_haiku, el): el
                    for el in candidatos
                }
                for future in as_completed(futures):
                    el = futures[future]
                    if future.result():
                        aprobados.append(el)

            orden_doc = {el["nombre"]: idx for idx, el in enumerate(elementos)}
            aprobados.sort(key=lambda el: orden_doc.get(el["nombre"], 0))
            elementos = aprobados
            for i, el in enumerate(elementos):
                el["id"] = i

    # ── Phase 6: valor pedagógico (razonador Sonnet, opt-in) ───────────────
    if elementos and analizar_advertencias:
        workers = min(len(elementos), _MAX_ADVERTENCIA_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(evaluar_advertencia, el): el
                for el in elementos
            }
            for future in as_completed(futures):
                el = futures[future]
                el["advertencia"] = future.result()

    return elementos
