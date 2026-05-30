"""Generacion de HTML interactivo autocontenido con Chart.js.

Pipeline:
  1. Para cada elemento seleccionado por el profesor, llamar a Sonnet
     (MODEL_SMART) con PROMPT_GENERADOR_HTML + build_generador_message()
     para generar el bloque HTML del panel (sliders, Chart.js, JS).
     Las llamadas se hacen en paralelo con ThreadPoolExecutor (max 4 workers).
     El orden original se preserva por indice, no por orden de finalizacion.
  2. Envolver los bloques en una pagina HTML fija (template Python con
     marcadores <!--MARKER-->) que incluye:
     - MathJax y Chart.js CDN una sola vez en <head>
     - Sistema de pestanas CSS puro (radio inputs + labels + ~ selector)
     - Header con titulo y footer con atribucion
  3. Devolver el HTML como string listo para escribir a disco.

Restricciones de diseno (no negociables):
  - El HTML final funciona sin servidor (abre directamente en navegador).
  - MathJax y Chart.js se cargan UNA sola vez en <head>.
  - Los bloques de Sonnet no deben incluir CDN ni tags html/head/body.
  - Los IDs de cada bloque llevan prefijo bloque_{slug}_ para evitar
    conflictos al concatenar varios paneles.
  - Si la llamada a la API falla para un elemento, se inserta un panel
    de error visible sin interrumpir la generacion de los demas.
"""

from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    MODEL_SMART,
    REQUEST_TIMEOUT_SECONDS,
)
from prompts import PROMPT_GENERADOR_HTML, build_generador_message


_MAX_RETRIES = 2
_MAX_WORKERS = 4  # llamadas Sonnet simultaneas maximas


# ---------------------------------------------------------------------------
# Helper: slug
# ---------------------------------------------------------------------------

def _slug(nombre: str) -> str:
    """Convert a display name to a URL/HTML-ID-safe lowercase slug.

    Removes diacritics, lowercases, replaces any run of non-alphanumeric
    characters with a single hyphen, and strips leading/trailing hyphens.

    Args:
        nombre: Display name (e.g. "Ley de Hooke").

    Returns:
        Slug string (e.g. "ley-de-hooke"). Falls back to "elemento" if
        the result would otherwise be empty.

    Examples:
        >>> _slug("Ecuación de Bernoulli")
        'ecuacion-de-bernoulli'
        >>> _slug("E = mc²")
        'e-mc-'
    """
    normalized = unicodedata.normalize("NFD", nombre)
    without_accents = "".join(
        c for c in normalized if unicodedata.category(c) != "Mn"
    )
    slug = re.sub(r"[^a-z0-9]+", "-", without_accents.lower()).strip("-")
    return slug or "elemento"


# ---------------------------------------------------------------------------
# HTML container template
#
# Uses <!--MARKER--> placeholders instead of str.format() so that the CSS
# curly braces do not need escaping. Replacements are applied via str.replace().
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title><!--TITULO--></title>
  <!-- CDN cargados una sola vez: los bloques individuales no deben incluirlos -->
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: system-ui, -apple-system, sans-serif;
      background: #F7F5F0;
      color: #2C2C2A;
      line-height: 1.6;
    }

    /* ---- Page header ---- */
    .page-header {
      background: #185FA5;
      color: #fff;
      padding: 2rem 2.5rem 1.5rem;
    }
    .page-header h1 {
      font-size: 1.75rem;
      font-weight: 700;
      margin-bottom: 0.25rem;
    }
    .page-header .subtitle {
      font-size: 0.875rem;
      opacity: 0.8;
    }

    /* ---- CSS-only tab system ----
       Radio inputs must precede .tabs-wrapper in the DOM so the
       general sibling combinator (~) can reach it from :checked. */
    .tab-inputs { display: none; }

    .tabs-wrapper {
      max-width: 960px;
      margin: 2rem auto;
      padding: 0 1.5rem 4rem;
    }

    .tab-labels {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      border-bottom: 2px solid #D3D1C7;
      padding-bottom: 0.5rem;
      margin-bottom: 1.75rem;
    }

    .tab-label {
      cursor: pointer;
      padding: 0.45rem 1rem;
      border-radius: 4px 4px 0 0;
      font-size: 0.875rem;
      font-weight: 500;
      color: #5F5E5A;
      border: 1px solid transparent;
      border-bottom: none;
      transition: color 0.15s, background 0.15s;
    }
    .tab-label:hover { color: #185FA5; background: #E6F1FB; }

    .tab-panel { display: none; }

    /* Per-element active/show rules injected below */
<!--TAB_CSS-->

    /* ---- Page footer ---- */
    .page-footer {
      text-align: center;
      padding: 2rem;
      font-size: 0.8rem;
      color: #888780;
      border-top: 1px solid #D3D1C7;
      margin-top: 3rem;
    }
  </style>
</head>
<body>

<!-- Hidden radio inputs BEFORE the wrapper so ~ selector works -->
<!--TAB_INPUTS-->

<header class="page-header">
  <h1><!--TITULO--></h1>
  <div class="subtitle">Material interactivo &mdash; Agente Presentaci&oacute;n</div>
</header>

<div class="tabs-wrapper">
  <nav class="tab-labels">
<!--TAB_LABELS-->
  </nav>

<!--TAB_PANELS-->
</div>

<footer class="page-footer">
  Generado a partir del material original del profesor.
</footer>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# API call: generate one HTML block
# ---------------------------------------------------------------------------

def _is_valid_html(text: str) -> bool:
    """Return True if the text looks like an HTML fragment."""
    return bool(text) and "<" in text and ">" in text


def _generar_bloque(elemento: dict, idx: int) -> tuple[int, str]:
    """Call Sonnet to generate the interactive HTML panel for one element.

    Retries up to _MAX_RETRIES times if the response does not look like
    valid HTML. On final failure, returns a styled error panel so the rest
    of the page can still be assembled.

    Args:
        elemento: Element dict. Required keys: nombre, expresion, contexto.
                  Optional: variables_entrada (list[dict] with nombre,
                  unidades, min, max), variable_salida (dict with nombre,
                  unidades). Both default to safe values if absent.
        idx: Original position in the elementos list. Preserved and returned
             so parallel results can be sorted back into document order.

    Returns:
        (idx, html_block) where html_block is either the Sonnet-generated
        HTML fragment or an error panel div.
    """
    nombre = elemento.get("nombre", f"Elemento {idx + 1}")
    latex = elemento.get("expresion", "")
    contexto = elemento.get("contexto", "")
    variables_entrada: list[dict] = elemento.get("variables_entrada", [])
    variable_salida: dict = elemento.get(
        "variable_salida", {"nombre": "resultado", "unidades": ""}
    )

    user_msg = build_generador_message(
        nombre=nombre,
        latex=latex,
        variables_entrada=variables_entrada,
        variable_salida=variable_salida,
        contexto=contexto,
    )

    last_exc: Exception | None = None
    # Instantiate once per element call, not per retry attempt
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=float(REQUEST_TIMEOUT_SECONDS),
    )

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL_SMART,
                max_tokens=4096,
                system=PROMPT_GENERADOR_HTML,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text.strip()

            # Strip accidental backtick code fences despite prompt instructions
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw).strip()

            if _is_valid_html(raw):
                return idx, raw

            last_exc = ValueError(
                f"Intento {attempt + 1}: respuesta sin HTML valido "
                f"(primeros 120 chars: {raw[:120]!r})"
            )

        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    # All retries exhausted — return visible error panel
    slug = _slug(nombre)
    nombre_esc = nombre.replace("<", "&lt;").replace(">", "&gt;")
    error_esc = str(last_exc).replace("<", "&lt;").replace(">", "&gt;")
    error_html = (
        f'<div id="bloque_{slug}_error" '
        'style="background:#FEE2E2;border-left:4px solid #DC2626;'
        'padding:1rem 1.25rem;border-radius:6px;margin:1rem 0;">'
        f'<strong>Error al generar &laquo;{nombre_esc}&raquo;</strong><br><br>'
        f'<code style="font-size:0.85rem;white-space:pre-wrap">{error_esc}</code>'
        "</div>"
    )
    return idx, error_html


# ---------------------------------------------------------------------------
# Assembly: wrap blocks in the HTML page container
# ---------------------------------------------------------------------------

def _construir_pagina(bloques: list[tuple[str, str]], titulo: str) -> str:
    """Wrap generated HTML blocks in the full page container.

    Builds the CSS-only tab navigation (one tab per block), injects the
    per-tab active/show CSS rules, and fills the <!--MARKER--> placeholders
    in _HTML_TEMPLATE.

    Args:
        bloques: Ordered list of (nombre, html_block) pairs.
        titulo: Page title for <title> and the visible header.

    Returns:
        Complete HTML string ready to write to disk.
    """
    titulo_esc = (
        titulo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )

    inputs_parts: list[str] = []
    labels_parts: list[str] = []
    panels_parts: list[str] = []
    css_parts: list[str] = []

    for i, (nombre, html_block) in enumerate(bloques):
        slug = _slug(nombre)
        input_id = f"tab-input-{slug}"
        panel_id = f"tab-panel-{slug}"
        nombre_esc = nombre.replace("<", "&lt;").replace(">", "&gt;")
        checked = " checked" if i == 0 else ""

        inputs_parts.append(
            f'<input class="tab-inputs" type="radio" name="tabs"'
            f' id="{input_id}"{checked}>'
        )
        labels_parts.append(
            f'    <label class="tab-label" for="{input_id}">{nombre_esc}</label>'
        )
        panels_parts.append(
            f'  <section class="tab-panel" id="{panel_id}">\n'
            f"{html_block}\n"
            f"  </section>"
        )

        # Active tab label
        css_parts.append(
            f'    #{input_id}:checked ~ .tabs-wrapper'
            f' .tab-label[for="{input_id}"] {{'
            f" color: #185FA5; background: #E6F1FB; font-weight: 600;"
            f" border-color: #D3D1C7 #D3D1C7 #F7F5F0; }}"
        )
        # Show matching panel
        css_parts.append(
            f"    #{input_id}:checked ~ .tabs-wrapper #{panel_id}"
            f" {{ display: block; }}"
        )

    html = _HTML_TEMPLATE
    html = html.replace("<!--TITULO-->", titulo_esc)
    html = html.replace("<!--TAB_INPUTS-->", "\n".join(inputs_parts))
    html = html.replace("<!--TAB_LABELS-->", "\n".join(labels_parts))
    html = html.replace("<!--TAB_PANELS-->", "\n".join(panels_parts))
    html = html.replace("<!--TAB_CSS-->", "\n".join(css_parts))
    return html


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generar_html(
    elementos: list[dict],
    markdown_completo: str,
    titulo_tema: str = "Material interactivo",
) -> str:
    """Generate a self-contained interactive HTML page from selected elements.

    Calls Sonnet (MODEL_SMART) in parallel — up to _MAX_WORKERS concurrent
    requests — to generate one interactive HTML panel per element. Preserves
    original element order regardless of API completion order.

    The HTML container (head, tab navigation, page header, footer) is built
    from a fixed Python template. MathJax and Chart.js CDNs appear once in
    <head>; Sonnet-generated blocks must not include them (enforced via the
    IMPORTANTE section of PROMPT_GENERADOR_HTML).

    Args:
        elementos: List of element dicts. Each must have: nombre, expresion,
                   contexto. Optional: variables_entrada (list[dict] with
                   nombre, unidades, min, max), variable_salida (dict with
                   nombre, unidades). Missing optional fields use safe defaults.
        markdown_completo: Full markdown source of the tema. Available for
                           future enrichment steps; not used in this version.
        titulo_tema: Text shown in the browser tab and the blue page header.

    Returns:
        Complete HTML string. Openable directly in any browser without a
        server. All styles and scripts are inline except the two CDNs.

    Raises:
        ValueError: If elementos is empty.
    """
    if not elementos:
        raise ValueError("La lista de elementos esta vacia — nada que generar.")

    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY no encontrada. "
            "Añade tu clave al archivo .env: ANTHROPIC_API_KEY=sk-ant-..."
        )

    resultados: list[tuple[int, str]] = []
    workers = min(len(elementos), _MAX_WORKERS)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_generar_bloque, el, i): i
            for i, el in enumerate(elementos)
        }
        for future in as_completed(futures):
            resultados.append(future.result())

    # Restore document order
    resultados.sort(key=lambda t: t[0])

    bloques: list[tuple[str, str]] = [
        (elementos[i].get("nombre", f"Elemento {i + 1}"), html_block)
        for i, html_block in resultados
    ]

    return _construir_pagina(bloques, titulo_tema)
