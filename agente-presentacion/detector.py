"""Deteccion de secciones con contenido matematico en Markdown.

Pipeline:
  1. Detectar todos los elementos matematicos individuales (regex):
     - Bloques LaTeX $$...$$
     - Inline $...$ (con filtros de trivialidad)
     - Tablas Markdown con contenido numerico
  2. Agrupar todos los elementos de la misma seccion (## / ###) en un
     unico elemento. Nombre del elemento = titulo del encabezado.
  3. Devolver un elemento por seccion con contenido matematico.

Cada elemento devuelto tiene:
    id         (int)  — indice 0-based
    tipo       (str)  — "relacion" | "ecuacion" | "tabla"
                        "relacion" si la seccion contiene alguna relacion
                        parametrica; "tabla" si todo son tablas; "ecuacion"
                        en otro caso.
    nombre     (str)  — titulo del encabezado de la seccion
    expresion  (str)  — todas las expresiones de la seccion concatenadas,
                        cada una envuelta en $$...$$ o $...$ segun tipo
    contexto   (str)  — texto completo de la seccion (max 3000 chars)
    seccion    (str)  — mismo que nombre
    es_bloque  (bool) — True siempre (nivel de seccion)

Nota sobre PROMPT_DETECTOR_INTERACTIVIDAD (prompts.py):
  El prompt esta definido para una posible fase de desambiguacion Haiku
  (clasificar tipo y nombre cuando la regex no puede determinarlo con
  confianza). En el diseno actual la agrupacion por seccion hace que el
  nombre venga siempre del encabezado Markdown, eliminando la ambiguedad.
  La llamada a Haiku no esta cableada — la deteccion es 100% determinista.

  TODO: integrar llamada a Haiku (PROMPT_DETECTOR_INTERACTIVIDAD) para
  secciones sin encabezado o con nombre demasiado generico (< 3 palabras).
"""

from __future__ import annotations

import re
from typing import Any

from config import (
    CONTEXTO_CHARS,
    MIN_LATEX_CHARS,
    MIN_VARIABLES_FOR_RELACION,
)

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
# Funcion principal
# ---------------------------------------------------------------------------

def detectar_elementos(markdown_text: str) -> list[dict[str, Any]]:
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
        if not expr:
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
        })

    return elementos
