"""Generacion del HTML de presentacion completa del tema.

Tercer modo de output del Agente Presentacion: un documento HTML scrollable
y autocontenido que integra TODA la teoria del Markdown curado con los
bloques interactivos (solo las ecuaciones seleccionadas por el profesor)
insertados en su posicion narrativa correcta.

Pipeline:
  1. Strip de frontmatter YAML y extraccion del titulo (H1).
  2. Division del documento en secciones por encabezado H2.
  3. Por cada elemento seleccionado: localizar la seccion H2 y el offset
     donde aparece su primera expresion (insercion inmediatamente despues
     del bloque Markdown que la presenta).
  4. Generacion de los bloques interactivos reutilizando
     generador_html._generar_bloque() — mismo razonador, mismos 7 patrones,
     misma tabla de variables, mismos reintentos y validacion. El listener
     DOMContentLoaded propio de cada bloque se elimina al embeber: en la
     presentacion la inicializacion es lazy por viewport
     (IntersectionObserver del contenedor).
  5. Marcadores [FIGURA: ...] sin bloque interactivo aprobado quedan como
     placeholder gris (mismo criterio que el PDF). No hay generacion
     automatica de figuras: si el profesor quiere una figura representada,
     la pide explicitamente en el taller, que es el unico camino con ciclo
     de revision (preview -> refinar -> aprobar) de todo el agente.
  6. Render Markdown -> HTML por segmentos, protegiendo LaTeX para MathJax,
     e intercalando los bloques interactivos en su offset.
  7. Ensamblado: sidebar con indice de H2 + scroll-spy, navegacion
     anterior/siguiente por seccion, boton volver arriba. MathJax y
     Chart.js se cargan UNA sola vez en <head>.

Restricciones (no negociables):
  - El contenido textual procede exclusivamente del Markdown del profesor.
  - Ninguna figura se genera sin que el profesor la haya pedido y aprobado
    en el taller. Antes (hasta 2026-06) existia un generador de SVG
    esquematicos vía Haiku para figuras sin bloque interactivo; se elimino
    porque no tenia paso de revision: un esquema generado mal no se podia
    corregir antes de llegar al documento final. Ver agente-presentacion/CLAUDE.md.
  - Los bloques interactivos no se duplican: se reutiliza la logica de
    generador_html sin copiarla.
"""

from __future__ import annotations

import base64
import html as html_lib
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import markdown as md_lib

from prs_config import ANTHROPIC_API_KEY
from generador_html import _generar_bloque, _slug

logger = logging.getLogger(__name__)

# La presentación genera más bloques Sonnet por documento que el HTML por
# pestañas (todas las secciones del tema): 2 workers para no agotar el
# límite de output tokens/min de la organización (429).
_MAX_WORKERS = 2

# ---------------------------------------------------------------------------
# Regex de estructura Markdown
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
_TEMA_DETECTADO_RE = re.compile(r"^tema_detectado:\s*(.+)$", re.MULTILINE)
_H1_RE = re.compile(r"^#\s+(?!#)(.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(?!#)(.+)$", re.MULTILINE)
_BLOCK_LATEX_RE = re.compile(r"\$\$([\s\S]+?)\$\$")
_INLINE_LATEX_RE = re.compile(r"(?<!\$)\$([^$\n]+?)\$(?!\$)")
_FIGURA_RE = re.compile(r"\[FIGURA:\s*([^\]]+)\]")
_TEXTO_ILEGIBLE_RE = re.compile(r"\[TEXTO_ILEGIBLE\]")
_FIGURA_ANCLA_RE = re.compile(r"^\[FIGURA:\s*(.+)\]$", re.IGNORECASE)

# Emojis de marcado interno del Agente Contenido (p. ej. "> 💡 *Resultado:*").
# Se eliminan del output porque la presentacion es material academico; el
# texto que acompanan se conserva integro.
_EMOJI_MARCADOR_RE = re.compile(r"[\U0001F4A1\U0001F50D⚠⚡✨✅❌\U0001F4CC]️?\s?")

# Listener de autoarranque que PROMPT_GENERADOR_HTML exige a cada bloque
# (pensado para el HTML interactivo por pestanas). En la presentacion el
# arranque es por viewport, asi que se elimina al embeber el bloque.
_SELF_INIT_RE = re.compile(
    r"(?://[^\n]*\n\s*)?document\.addEventListener\(\s*['\"`]DOMContentLoaded['\"`]\s*,"
    r"\s*(?:function\s*\(\s*\)|\(\s*\)\s*=>)\s*\{[\s\S]*?\}\s*\)\s*;?",
)



# ---------------------------------------------------------------------------
# Particion del documento en secciones H2
# ---------------------------------------------------------------------------

def _strip_frontmatter(markdown_text: str) -> str:
    """Elimina el frontmatter YAML inicial si existe."""
    return _FRONTMATTER_RE.sub("", markdown_text, count=1)


def _extraer_titulo(markdown_text: str, fallback: str) -> str:
    """Devuelve el texto del primer H1, o el fallback si no hay H1."""
    m = _H1_RE.search(markdown_text)
    return m.group(1).strip() if m else fallback


def _extraer_asignatura(markdown_text: str, fallback: str) -> str:
    """Nombre de la asignatura: tema_detectado del frontmatter, o el H1."""
    m_fm = _FRONTMATTER_RE.match(markdown_text)
    if m_fm:
        m = _TEMA_DETECTADO_RE.search(m_fm.group(0))
        if m:
            return m.group(1).strip()
    m = _H1_RE.search(markdown_text)
    return m.group(1).strip() if m else fallback


# ---------------------------------------------------------------------------
# Logo de la Universidad de Oviedo (assets/logo_uniovi.png)
# ---------------------------------------------------------------------------

_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "logo_uniovi.png"
)


def _cargar_logo_base64() -> str | None:
    """Logo UO en base64, o None si el archivo no existe o no es legible.

    Nunca lanza: si el logo falta, la cabecera degrada a solo texto.
    """
    try:
        with open(_LOGO_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None


def _dividir_secciones(markdown_text: str) -> list[dict]:
    """Divide el documento por H2 en [{titulo, body}], en orden.

    El texto anterior al primer H2 (excluyendo el H1) se devuelve como
    seccion "Introducción" si no esta vacio.
    """
    headings = list(_H2_RE.finditer(markdown_text))
    secciones: list[dict] = []

    preamble_end = headings[0].start() if headings else len(markdown_text)
    preamble = _H1_RE.sub("", markdown_text[:preamble_end], count=1).strip()
    if preamble:
        secciones.append({"titulo": "Introducción", "body": preamble})

    for i, m in enumerate(headings):
        body_start = m.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown_text)
        secciones.append({
            "titulo": m.group(1).strip(),
            "body": markdown_text[body_start:body_end].strip("\n"),
        })
    return secciones


# ---------------------------------------------------------------------------
# Localizacion del punto de insercion de cada bloque interactivo
# ---------------------------------------------------------------------------

def _primera_expresion(elemento: dict) -> tuple[str | None, bool]:
    """Primera expresion del elemento ($$ bloque o $ inline) y su tipo."""
    expresion = elemento.get("expresion", "")
    m = _BLOCK_LATEX_RE.search(expresion)
    if m:
        return m.group(1).strip(), True
    m = _INLINE_LATEX_RE.search(expresion)
    if m:
        return m.group(1).strip(), False
    return None, False


_SIGUIENTE_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)


def _fin_de_subseccion(body: str, pos: int) -> int:
    """Extiende `pos` hasta el siguiente encabezado del body (o su final).

    Asi el bloque interactivo se inserta despues de TODO el contenido
    textual que presenta la ecuacion (incluidas las lineas "Donde ..."
    que siguen a la expresion), no en mitad de la explicacion.
    """
    m = _SIGUIENTE_HEADING_RE.search(body, pos)
    return m.start() if m else len(body)


def _offset_en_body(body: str, elemento: dict) -> int | None:
    """Offset de insercion del bloque interactivo dentro del body.

    Localiza la primera expresion del elemento ($$...$$ o inline) y
    devuelve el final de la subseccion que la contiene. None si la
    expresion no aparece en este body.
    """
    expr, es_bloque = _primera_expresion(elemento)
    if not expr:
        return None
    if es_bloque:
        for m in _BLOCK_LATEX_RE.finditer(body):
            if m.group(1).strip() == expr:
                return _fin_de_subseccion(body, m.end())
        return None
    idx = body.find(expr)
    if idx == -1:
        return None
    return _fin_de_subseccion(body, idx)


def _asignar_a_secciones(
    secciones: list[dict], elementos: list[dict]
) -> dict[int, list[tuple[int, dict]]]:
    """Asigna cada elemento a (seccion, offset) por su primera expresion.

    Desambiguacion: si el heading `seccion` del elemento (### del detector)
    aparece en el body de una seccion H2, se busca primero ahi. Elementos
    no localizados van al final de la ultima seccion (con warning).

    Returns:
        {indice_seccion: [(offset_en_body, elemento), ...]}
    """
    asignaciones: dict[int, list[tuple[int, dict]]] = {}

    def _add(idx_seccion: int, offset: int, elemento: dict) -> None:
        asignaciones.setdefault(idx_seccion, []).append((offset, elemento))

    for elemento in elementos:
        heading = (elemento.get("seccion") or "").strip()
        candidatos = list(range(len(secciones)))
        if heading:
            con_heading = [
                i for i, s in enumerate(secciones)
                if re.search(
                    rf"^#{{3,4}}\s+{re.escape(heading)}\s*$",
                    s["body"],
                    re.MULTILINE,
                )
                or s["titulo"] == heading
            ]
            candidatos = con_heading + [i for i in candidatos if i not in con_heading]

        colocado = False
        for i in candidatos:
            offset = _offset_en_body(secciones[i]["body"], elemento)
            if offset is not None:
                _add(i, offset, elemento)
                colocado = True
                break

        if not colocado and secciones:
            logger.warning(
                "[PRESENTACION] No se localizó la expresión de %r — "
                "bloque añadido al final de la última sección",
                elemento.get("nombre", ""),
            )
            _add(len(secciones) - 1, len(secciones[-1]["body"]), elemento)

    return asignaciones


# ---------------------------------------------------------------------------
# Render Markdown -> HTML (con proteccion de LaTeX y marcadores)
# ---------------------------------------------------------------------------

def _render_markdown(texto: str, figuras_html: dict[str, str]) -> str:
    """Convierte un segmento Markdown a HTML para la presentacion.

    Protege LaTeX con tokens para que la libreria markdown no lo altere y
    lo restaura como delimitadores MathJax. Los marcadores [FIGURA: ...] y
    [TEXTO_ILEGIBLE] se sustituyen por su HTML (placeholder, SVG o aviso).

    Args:
        texto: Segmento de Markdown (nunca contiene encabezados H1/H2).
        figuras_html: {descripcion_figura: html} con el render decidido
            para cada figura del documento (placeholder gris o SVG).
    """
    texto = _EMOJI_MARCADOR_RE.sub("", texto)
    texto = re.sub(r"\[ECUACION_PARCIAL:[^\]]+\]", "", texto)
    texto = re.sub(r"\[ECUACION\]", "", texto)

    tokens: dict[str, str] = {}

    def _token(html_final: str) -> str:
        key = f"xxPRESTOKEN{len(tokens)}xx"
        tokens[key] = html_final
        return key

    def _figura(m: re.Match[str]) -> str:
        descripcion = m.group(1).strip()
        return _token(figuras_html.get(
            descripcion, _figura_placeholder(descripcion)
        ))

    texto = _FIGURA_RE.sub(_figura, texto)
    texto = _TEXTO_ILEGIBLE_RE.sub(
        lambda m: _token(
            '<span class="texto-ilegible">[fragmento ilegible en el '
            "material original]</span>"
        ),
        texto,
    )
    texto = _BLOCK_LATEX_RE.sub(
        lambda m: _token(
            '<div class="ecuacion-display">\\['
            + html_lib.escape(m.group(1).strip())
            + "\\]</div>"
        ),
        texto,
    )
    texto = _INLINE_LATEX_RE.sub(
        lambda m: _token("\\(" + html_lib.escape(m.group(1).strip()) + "\\)"),
        texto,
    )

    html_out = md_lib.markdown(texto, extensions=["tables", "fenced_code"])

    for key, html_final in tokens.items():
        # El token puede llegar envuelto en <p>...</p> si iba solo en linea
        html_out = html_out.replace(f"<p>{key}</p>", html_final)
        html_out = html_out.replace(key, html_final)
    return html_out


def _figura_placeholder(descripcion: str) -> str:
    """Placeholder gris para [FIGURA: ...] — mismo criterio que el PDF."""
    return (
        '<div class="figura-placeholder">'
        '<span class="figura-placeholder-etiqueta">Figura del material original</span>'
        f"<p>{html_lib.escape(descripcion)}</p>"
        "</div>"
    )


def _generar_figuras(
    secciones: list[dict],
    figura_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Decide el render de cada [FIGURA: ...] del documento.

    Las figuras con un fragmento aprobado en el taller (override) se
    insertan directamente. El resto se queda siempre como placeholder gris
    — no hay generación automática de figuras sin que el profesor la pida
    explícitamente en el taller, porque ese es el único camino con ciclo de
    revisión (preview -> refinar -> aprobar) de todo el agente.
    """
    figuras_html: dict[str, str] = {}
    figura_overrides = figura_overrides or {}

    for seccion in secciones:
        for m in _FIGURA_RE.finditer(seccion["body"]):
            descripcion = m.group(1).strip()
            if descripcion in figuras_html:
                continue
            figuras_html[descripcion] = figura_overrides.get(
                descripcion, _figura_placeholder(descripcion)
            )

    return figuras_html


# ---------------------------------------------------------------------------
# Bloques interactivos (reutiliza generador_html)
# ---------------------------------------------------------------------------

def _preparar_bloque(html_bloque: str, slug: str) -> str:
    """Adapta un bloque de generador_html al contenedor de presentacion.

    Elimina el listener DOMContentLoaded de autoarranque (la presentacion
    inicializa por viewport con IntersectionObserver) y envuelve el bloque
    en la card "Explorador interactivo" diferenciada del texto.
    """
    sin_autoarranque = _SELF_INIT_RE.sub("", html_bloque)
    return (
        f'<div class="bloque-interactivo" data-slug="{slug}"'
        ' data-initialized="false">'
        '<div class="bloque-interactivo-cabecera">Explorador interactivo</div>'
        f"\n{sin_autoarranque}\n"
        "</div>"
    )


def _generar_bloques(
    elementos: list[dict],
    verbose: bool,
    texto_original: str | None,
) -> dict[int, str]:
    """Genera los bloques interactivos en paralelo: {id(elemento): html}."""
    if not elementos:
        return {}
    resultados: dict[int, str] = {}
    workers = min(len(elementos), _MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _generar_bloque, el, i, verbose, texto_original,
                requiere_autoarranque=False,
            ): i
            for i, el in enumerate(elementos)
        }
        for future in as_completed(futures):
            idx, html_bloque = future.result()
            elemento = elementos[idx]
            slug = _slug(elemento.get("nombre", f"Elemento {idx + 1}"))
            resultados[id(elemento)] = _preparar_bloque(html_bloque, slug)
    return resultados


# ---------------------------------------------------------------------------
# Ensamblado de cada seccion
# ---------------------------------------------------------------------------

def _render_seccion(
    seccion: dict,
    inserciones: list[tuple[int, dict]],
    bloques_html: dict[int, str],
    figuras_html: dict[str, str],
) -> str:
    """Renderiza el body de una seccion intercalando bloques interactivos."""
    body = seccion["body"]
    inserciones = sorted(inserciones, key=lambda t: t[0])

    partes: list[str] = []
    cursor = 0
    for offset, elemento in inserciones:
        offset = max(cursor, min(offset, len(body)))
        segmento = body[cursor:offset]
        if segmento.strip():
            partes.append(_render_markdown(segmento, figuras_html))
        partes.append(bloques_html.get(id(elemento), ""))
        cursor = offset
    resto = body[cursor:]
    if resto.strip():
        partes.append(_render_markdown(resto, figuras_html))
    return "\n".join(partes)


def _nav_seccion(idx: int, secciones: list[dict]) -> str:
    """Botones anterior/siguiente al pie de cada seccion."""
    partes = ['<nav class="seccion-nav">']
    if idx > 0:
        titulo_prev = html_lib.escape(secciones[idx - 1]["titulo"])
        partes.append(
            f'<a class="seccion-nav-link" href="#seccion-{idx - 1}">'
            f"&larr; {titulo_prev}</a>"
        )
    else:
        partes.append("<span></span>")
    if idx < len(secciones) - 1:
        titulo_next = html_lib.escape(secciones[idx + 1]["titulo"])
        partes.append(
            f'<a class="seccion-nav-link" href="#seccion-{idx + 1}">'
            f"{titulo_next} &rarr;</a>"
        )
    else:
        partes.append("<span></span>")
    partes.append("</nav>")
    return "".join(partes)


# ---------------------------------------------------------------------------
# Template de pagina (marcadores <!--X--> como en generador_html)
# ---------------------------------------------------------------------------

_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title><!--TITULO--></title>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
  <!-- CDN cargados una sola vez: los bloques individuales no deben incluirlos -->
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    html { scroll-behavior: smooth; }

    body {
      font-family: 'DM Sans', sans-serif;
      background: #F7F5F0;
      color: #1A1A1A;
      line-height: 1.65;
    }

    .page-header {
      background: #003366;
      color: #FFFFFF;
      padding: 1.25rem 2rem;
      display: flex;
      align-items: center;
      gap: 1.5rem;
      border-bottom: 3px solid #C8A951;
    }
    .page-header h1 { font-size: 22px; font-weight: 500; margin-bottom: 0.25rem; }
    .page-header .subtitle { font-size: 14px; opacity: 0.75; }
    /* Chip blanco para que el logo (oscuro, fondo transparente) sea legible
       sobre la cabecera azul #003366. */
    .page-header-logo {
      background: #FFFFFF;
      border-radius: 8px;
      padding: 8px 14px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
    }
    .page-header-logo img { height: 64px; width: auto; display: block; }

    .layout {
      display: flex;
      align-items: flex-start;
      gap: 2rem;
      max-width: 1180px;
      margin: 0 auto;
      padding: 2rem 1.5rem 4rem;
    }

    /* ---- Indice lateral ---- */
    .indice {
      position: sticky;
      top: 1.5rem;
      width: 250px;
      flex-shrink: 0;
      background: #FFFFFF;
      border: 0.5px solid rgba(0,0,0,0.08);
      border-radius: 12px;
      padding: 1rem 0.75rem;
      max-height: calc(100vh - 3rem);
      overflow-y: auto;
    }
    .indice-titulo {
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.08em;
      color: #9A9890;
      padding: 0 10px 8px;
    }
    .indice-link {
      display: block;
      padding: 6px 10px;
      font-size: 13px;
      color: #6B6860;
      text-decoration: none;
      border-radius: 8px;
      border-left: 2px solid transparent;
    }
    .indice-link:hover { background: rgba(0,0,0,0.04); }
    .indice-link.activa {
      color: #185FA5;
      background: #F0EEE9;
      border-left-color: #185FA5;
      font-weight: 500;
    }

    /* ---- Contenido ---- */
    .contenido { flex: 1; min-width: 0; }

    .seccion {
      background: #FFFFFF;
      border: 0.5px solid rgba(0,0,0,0.08);
      border-radius: 14px;
      padding: 2rem 2.25rem;
      margin-bottom: 1.5rem;
    }
    .eyebrow {
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.08em;
      color: #9A9890;
      margin-bottom: 0.4rem;
    }
    .seccion > h2 {
      font-family: 'Playfair Display', serif;
      font-size: 26px;
      font-weight: 600;
      margin-bottom: 1.25rem;
    }
    .seccion h3 {
      font-size: 17px;
      font-weight: 500;
      color: #185FA5;
      margin: 1.5rem 0 0.6rem;
    }
    .seccion h4 {
      font-size: 14px;
      font-weight: 500;
      color: #1A1A1A;
      margin: 1.25rem 0 0.5rem;
    }
    .seccion p { font-size: 14.5px; color: #1A1A1A; margin-bottom: 0.85rem; }
    .seccion ul, .seccion ol { margin: 0 0 0.85rem 1.4rem; font-size: 14.5px; }
    .seccion li { margin-bottom: 0.3rem; }
    .seccion blockquote {
      border-left: 3px solid #D3D1C7;
      padding: 0.4rem 1rem;
      color: #6B6860;
      font-style: italic;
      margin: 0 0 0.85rem;
    }
    .seccion table {
      border-collapse: collapse;
      width: 100%;
      font-size: 13.5px;
      margin: 1rem 0 1.25rem;
    }
    .seccion th {
      color: #185FA5;
      text-align: left;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .seccion th, .seccion td {
      padding: 8px 12px;
      border: 0.5px solid #D3D1C7;
    }
    .seccion tbody tr:nth-child(even) td { background: #F7F5F0; }

    .ecuacion-display {
      text-align: center;
      padding: 0.75rem 0 1rem;
      font-size: 18px;
      overflow-x: auto;
    }

    .texto-ilegible { color: #9A9890; font-style: italic; }

    /* ---- Figuras ---- */
    .figura-placeholder {
      background: #EFEDE8;
      border: 1px dashed #C9C6BD;
      border-radius: 10px;
      padding: 1.25rem 1.5rem;
      margin: 1.25rem 0;
      color: #6B6860;
    }
    .figura-placeholder-etiqueta {
      display: block;
      text-transform: uppercase;
      font-size: 10px;
      letter-spacing: 0.08em;
      color: #9A9890;
      margin-bottom: 0.35rem;
    }
    .figura-placeholder p { font-size: 13px; font-style: italic; margin: 0; }

    /* ---- Bloque interactivo ---- */
    .bloque-interactivo {
      border-left: 3px solid #003366;
      background: #EEF2F7;
      border-radius: 0 12px 12px 0;
      padding: 1rem 1.25rem 1.25rem;
      margin: 1.5rem 0;
    }
    .bloque-interactivo-cabecera {
      text-transform: uppercase;
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.08em;
      color: #003366;
      margin-bottom: 0.75rem;
    }

    /* ---- Navegacion entre secciones ---- */
    .seccion-nav {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      margin-top: 1.75rem;
      padding-top: 1rem;
      border-top: 0.5px solid rgba(0,0,0,0.08);
    }
    .seccion-nav-link {
      font-size: 13px;
      color: #185FA5;
      text-decoration: none;
      padding: 6px 10px;
      border-radius: 8px;
    }
    .seccion-nav-link:hover { background: #F0EEE9; }

    #volver-arriba {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 42px;
      height: 42px;
      border-radius: 50%;
      background: #185FA5;
      color: #FFFFFF;
      border: none;
      cursor: pointer;
      font-size: 18px;
      display: none;
      align-items: center;
      justify-content: center;
    }
    #volver-arriba:hover { background: #0C447C; }

    .page-footer {
      text-align: center;
      padding: 2rem;
      font-size: 0.8rem;
      color: #9A9890;
      border-top: 0.5px solid rgba(0,0,0,0.08);
      margin-top: 3rem;
    }

    @media (max-width: 900px) {
      .indice { display: none; }
    }
  </style>
</head>
<body id="top">

<header class="page-header">
<!--LOGO-->
  <div>
    <h1><!--TITULO--></h1>
    <div class="subtitle"><!--ASIGNATURA--> &mdash; Universidad de Oviedo</div>
  </div>
</header>

<div class="layout">
  <nav class="indice" id="indice">
    <div class="indice-titulo">&Iacute;ndice del tema</div>
<!--INDICE-->
  </nav>

  <main class="contenido">
<!--SECCIONES-->
  </main>
</div>

<button id="volver-arriba" type="button" aria-label="Volver arriba">&uarr;</button>

<footer class="page-footer">
  Generado a partir del material original del profesor.
</footer>

<script>
(function () {
  function initBloque(card) {
    if (card.dataset.initialized === "true") return;
    var initName = "initBloque_" + card.dataset.slug;
    if (typeof window[initName] === "function") {
      try {
        window[initName]();
      } catch (e) {
        console.error("Error en " + initName + ":", e);
      }
    } else {
      console.error(
        "No se encontró la función " + initName +
        " — el bloque interactivo no puede inicializarse."
      );
    }
    card.dataset.initialized = "true";
  }

  function arrancarBloques() {
    var cards = Array.prototype.slice.call(
      document.querySelectorAll(".bloque-interactivo[data-slug]")
    );
    if (!("IntersectionObserver" in window)) {
      cards.forEach(initBloque);
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          initBloque(entry.target);
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: "300px 0px" });
    cards.forEach(function (card) { io.observe(card); });
  }

  function arrancarScrollSpy() {
    if (!("IntersectionObserver" in window)) return;
    var enlaces = {};
    document.querySelectorAll(".indice-link").forEach(function (a) {
      enlaces[a.getAttribute("href").slice(1)] = a;
    });
    var visibles = {};
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        visibles[entry.target.id] = entry.isIntersecting;
      });
      var activa = null;
      document.querySelectorAll(".seccion").forEach(function (s) {
        if (activa === null && visibles[s.id]) activa = s.id;
      });
      if (activa && enlaces[activa]) {
        Object.keys(enlaces).forEach(function (k) {
          enlaces[k].classList.remove("activa");
        });
        enlaces[activa].classList.add("activa");
      }
    }, { rootMargin: "-15% 0px -65% 0px" });
    document.querySelectorAll(".seccion").forEach(function (s) { io.observe(s); });
  }

  function arrancarVolverArriba() {
    var btn = document.getElementById("volver-arriba");
    if (!btn) return;
    window.addEventListener("scroll", function () {
      btn.style.display = window.scrollY > 600 ? "flex" : "none";
    });
    btn.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  function boot() {
    arrancarBloques();
    arrancarScrollSpy();
    arrancarVolverArriba();
  }

  function esperarMathJax() {
    if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
      MathJax.startup.promise.then(boot);
    } else {
      boot();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", esperarMathJax);
  } else {
    esperarMathJax();
  }
})();
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def generar_presentacion(
    markdown_completo: str,
    elementos_seleccionados: list[dict],
    tema_nombre: str = "Material docente",
    verbose: bool = True,
    texto_original: str | None = None,
) -> str:
    """Genera el HTML de presentacion completa del tema.

    Integra toda la teoria del Markdown (dividida en secciones H2) con los
    bloques interactivos de las ecuaciones seleccionadas por el profesor,
    insertados inmediatamente despues del bloque de contenido que las
    presenta. Las secciones sin ecuacion seleccionada llevan solo contenido
    textual (y, opcionalmente, un SVG esquematico para sus [FIGURA: ...]).

    Args:
        markdown_completo: Markdown curado completo (Agente Contenido).
        elementos_seleccionados: Elementos del detector marcados por el
            profesor. Puede ser una lista vacia (presentacion solo textual).
        tema_nombre: Titulo de respaldo si el Markdown no tiene H1.
        verbose: Propagado a la generacion de bloques (logging.debug).
        texto_original: Texto opcional del PDF/PPTX del profesor para el
            razonador de visualizacion.

    Returns:
        HTML autocontenido (string) listo para escribir a disco.

    Raises:
        ValueError: Si el Markdown esta vacio.
        RuntimeError: Si faltan credenciales y hay elementos seleccionados.
    """
    if not markdown_completo or not markdown_completo.strip():
        raise ValueError("El Markdown está vacío — nada que presentar.")

    if elementos_seleccionados and not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY no encontrada. "
            "Añade tu clave al archivo .env: ANTHROPIC_API_KEY=sk-ant-..."
        )

    texto = _strip_frontmatter(markdown_completo)
    titulo = _extraer_titulo(texto, tema_nombre)
    asignatura = _extraer_asignatura(markdown_completo, titulo)
    secciones = _dividir_secciones(texto)
    if not secciones:
        raise ValueError("No se encontraron secciones en el Markdown.")

    asignaciones = _asignar_a_secciones(secciones, elementos_seleccionados)
    bloques_html = _generar_bloques(
        elementos_seleccionados, verbose, texto_original
    )
    figuras_html = _generar_figuras(secciones)

    titulo_esc = html_lib.escape(titulo)

    # Desambiguación de títulos repetidos SOLO en el texto visible de la
    # sidebar: "Contenido teórico", "Contenido teórico (2)", ... Los IDs de
    # sección y el contenido del documento no cambian.
    veces_visto: dict[str, int] = {}
    etiquetas_indice: list[str] = []
    for seccion in secciones:
        titulo_sec = seccion["titulo"]
        veces_visto[titulo_sec] = veces_visto.get(titulo_sec, 0) + 1
        n = veces_visto[titulo_sec]
        etiquetas_indice.append(
            titulo_sec if n == 1 else f"{titulo_sec} ({n})"
        )

    indice_parts: list[str] = []
    secciones_parts: list[str] = []
    for i, seccion in enumerate(secciones):
        titulo_sec = html_lib.escape(seccion["titulo"])
        etiqueta = html_lib.escape(etiquetas_indice[i])
        indice_parts.append(
            f'    <a class="indice-link" href="#seccion-{i}">{etiqueta}</a>'
        )
        cuerpo = _render_seccion(
            seccion, asignaciones.get(i, []), bloques_html, figuras_html
        )
        secciones_parts.append(
            f'    <section class="seccion" id="seccion-{i}">\n'
            f'      <p class="eyebrow">Sección {i + 1} — {titulo_esc}</p>\n'
            f"      <h2>{titulo_sec}</h2>\n"
            f"{cuerpo}\n"
            f"{_nav_seccion(i, secciones)}\n"
            f"    </section>"
        )

    logo_b64 = _cargar_logo_base64()
    if logo_b64:
        logo_html = (
            '  <div class="page-header-logo">'
            '<img src="data:image/png;base64,' + logo_b64 + '" '
            'alt="Universidad de Oviedo"></div>'
        )
    else:
        logo_html = ""

    html_out = _PAGE_TEMPLATE
    html_out = html_out.replace("<!--TITULO-->", titulo_esc)
    html_out = html_out.replace("<!--ASIGNATURA-->", html_lib.escape(asignatura))
    html_out = html_out.replace("<!--LOGO-->", logo_html)
    html_out = html_out.replace("<!--INDICE-->", "\n".join(indice_parts))
    html_out = html_out.replace("<!--SECCIONES-->", "\n".join(secciones_parts))
    return html_out


def _localizar_offset_ancla(body: str, seccion_titulo: str, ancla: str) -> int:
    """Offset en el body donde insertar un fragmento HTML según el heading ancla."""
    ancla = (ancla or "").strip()
    if not ancla:
        return len(body)
    if ancla.lower() == seccion_titulo.strip().lower():
        return len(body)
    m = re.search(
        rf"^#{{3,4}}\s+{re.escape(ancla)}\s*$",
        body,
        re.MULTILINE | re.IGNORECASE,
    )
    if m:
        return _fin_de_subseccion(body, m.end())
    for m in re.finditer(r"^(#{3,4})\s+(.+)$", body, re.MULTILINE):
        if ancla.lower() in m.group(2).strip().lower():
            return _fin_de_subseccion(body, m.end())
    return len(body)


def _figura_ancla_descripcion(ancla: str) -> str | None:
    """Devuelve la descripción de figura si el ancla es un marcador [FIGURA: ...]."""
    m = _FIGURA_ANCLA_RE.match((ancla or "").strip())
    return m.group(1).strip() if m else None


def _preparar_figura_overrides(fragmentos: list[dict]) -> dict[str, str]:
    """Construye {descripcion_figura: html_preparado} para fragmentos anclados a figura."""
    overrides: dict[str, str] = {}
    for frag in sorted(fragmentos, key=lambda f: (f.get("orden", 0), f.get("id", 0))):
        ancla = (frag.get("seccion_ancla") or "").strip()
        desc = _figura_ancla_descripcion(ancla)
        if desc is None:
            continue
        html_raw = frag.get("html_fragment") or ""
        if not html_raw.strip():
            continue
        titulo = frag.get("titulo") or "Visualización"
        overrides[desc] = _preparar_bloque(html_raw, _slug(titulo))
    return overrides


def _asignar_fragmentos_a_secciones(
    secciones: list[dict],
    fragmentos: list[dict],
) -> dict[int, list[tuple[int, str]]]:
    """Asigna fragmentos HTML aprobados a secciones H2 del documento.

    Los fragmentos anclados a [FIGURA: ...] se omiten aquí — se manejan
    en _preparar_figura_overrides.
    """
    asignaciones: dict[int, list[tuple[int, str]]] = {}
    ordenados = sorted(fragmentos, key=lambda f: (f.get("orden", 0), f.get("id", 0)))

    for frag in ordenados:
        html_raw = frag.get("html_fragment") or ""
        if not html_raw.strip():
            continue
        titulo = frag.get("titulo") or "Visualización"
        slug = _slug(titulo)
        html_prep = _preparar_bloque(html_raw, slug)
        ancla = (frag.get("seccion_ancla") or "").strip()

        if _figura_ancla_descripcion(ancla) is not None:
            continue

        idx_destino: int | None = None
        offset = 0
        if ancla:
            for i, sec in enumerate(secciones):
                if ancla.lower() == sec["titulo"].strip().lower():
                    idx_destino = i
                    offset = _localizar_offset_ancla(sec["body"], sec["titulo"], ancla)
                    break
            if idx_destino is None:
                for i, sec in enumerate(secciones):
                    off = _localizar_offset_ancla(sec["body"], sec["titulo"], ancla)
                    if off < len(sec["body"]) or re.search(
                        rf"^#{{2,4}}\s+.*{re.escape(ancla)}",
                        sec["body"],
                        re.MULTILINE | re.IGNORECASE,
                    ):
                        idx_destino = i
                        offset = off
                        break

        if idx_destino is None and secciones:
            idx_destino = len(secciones) - 1
            offset = len(secciones[-1]["body"])
            logger.warning(
                "[PRESENTACION] Fragmento %r sin ancla clara — al final del bloque",
                titulo,
            )

        if idx_destino is not None:
            asignaciones.setdefault(idx_destino, []).append((offset, html_prep))

    return asignaciones


def _render_seccion_con_html(
    seccion: dict,
    inserciones: list[tuple[int, str]],
    figuras_html: dict[str, str],
) -> str:
    """Renderiza el body intercalando fragmentos HTML pregenerados."""
    body = seccion["body"]
    inserciones = sorted(inserciones, key=lambda t: t[0])
    partes: list[str] = []
    cursor = 0
    for offset, html_block in inserciones:
        offset = max(cursor, min(offset, len(body)))
        segmento = body[cursor:offset]
        if segmento.strip():
            partes.append(_render_markdown(segmento, figuras_html))
        partes.append(html_block)
        cursor = offset
    resto = body[cursor:]
    if resto.strip():
        partes.append(_render_markdown(resto, figuras_html))
    return "\n".join(partes)


def generar_presentacion_con_fragmentos(
    markdown_completo: str,
    fragmentos_aprobados: list[dict],
    tema_nombre: str = "Material docente",
) -> str:
    """Genera HTML de presentación completa con fragmentos interactivos ya aprobados.

    Args:
        markdown_completo: Markdown curado del bloque (Agente Contenido).
        fragmentos_aprobados: Lista de dicts con titulo, html_fragment, seccion_ancla, orden.
        tema_nombre: Título visible del documento.
    """
    if not markdown_completo or not markdown_completo.strip():
        raise ValueError("El Markdown está vacío — nada que presentar.")

    texto = _strip_frontmatter(markdown_completo)
    titulo = _extraer_titulo(texto, tema_nombre)
    asignatura = _extraer_asignatura(markdown_completo, titulo)
    secciones = _dividir_secciones(texto)
    if not secciones:
        raise ValueError("No se encontraron secciones en el Markdown.")

    figura_overrides = _preparar_figura_overrides(fragmentos_aprobados)
    asignaciones_html = _asignar_fragmentos_a_secciones(secciones, fragmentos_aprobados)
    figuras_html = _generar_figuras(secciones, figura_overrides)

    titulo_esc = html_lib.escape(titulo)
    veces_visto: dict[str, int] = {}
    etiquetas_indice: list[str] = []
    for seccion in secciones:
        titulo_sec = seccion["titulo"]
        veces_visto[titulo_sec] = veces_visto.get(titulo_sec, 0) + 1
        n = veces_visto[titulo_sec]
        etiquetas_indice.append(
            titulo_sec if n == 1 else f"{titulo_sec} ({n})"
        )

    indice_parts: list[str] = []
    secciones_parts: list[str] = []
    for i, seccion in enumerate(secciones):
        titulo_sec = html_lib.escape(seccion["titulo"])
        etiqueta = html_lib.escape(etiquetas_indice[i])
        indice_parts.append(
            f'    <a class="indice-link" href="#seccion-{i}">{etiqueta}</a>'
        )
        cuerpo = _render_seccion_con_html(
            seccion,
            asignaciones_html.get(i, []),
            figuras_html,
        )
        secciones_parts.append(
            f'    <section class="seccion" id="seccion-{i}">\n'
            f'      <p class="eyebrow">Sección {i + 1} — {titulo_esc}</p>\n'
            f"      <h2>{titulo_sec}</h2>\n"
            f"{cuerpo}\n"
            f"{_nav_seccion(i, secciones)}\n"
            f"    </section>"
        )

    logo_b64 = _cargar_logo_base64()
    if logo_b64:
        logo_html = (
            '  <div class="page-header-logo">'
            '<img src="data:image/png;base64,' + logo_b64 + '" '
            'alt="Universidad de Oviedo"></div>'
        )
    else:
        logo_html = ""

    html_out = _PAGE_TEMPLATE
    html_out = html_out.replace("<!--TITULO-->", titulo_esc)
    html_out = html_out.replace("<!--ASIGNATURA-->", html_lib.escape(asignatura))
    html_out = html_out.replace("<!--LOGO-->", logo_html)
    html_out = html_out.replace("<!--INDICE-->", "\n".join(indice_parts))
    html_out = html_out.replace("<!--SECCIONES-->", "\n".join(secciones_parts))
    return html_out
