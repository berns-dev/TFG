"""Generacion de HTML interactivo autocontenido con Chart.js.

Pipeline:
  1. Para cada elemento seleccionado por el profesor:
     a) Llamar a Sonnet (MODEL_SMART) con PROMPT_RAZONADOR_VISUALIZACION
        + build_razonador_message() para decidir el patrón de visualización.
     b) Parsear el XML <VISUALIZACION> de la respuesta.
     c) Llamar a Sonnet con PROMPT_GENERADOR_HTML + build_generador_message()
        para generar el bloque HTML adaptado al patrón elegido.
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

import base64
import json
import logging
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

from prs_config import (
    ANTHROPIC_API_KEY,
    MODEL_FAST,
    MODEL_SMART,
    REQUEST_TIMEOUT_SECONDS,
)
from prs_prompts import (
    PROMPT_DESCRIPCION_VARIABLES,
    PROMPT_GENERADOR_HTML,
    PROMPT_RAZONADOR_VISUALIZACION,
    build_descripcion_variables_message,
    build_generador_message,
    build_razonador_message,
)

_MONOREPO_ROOT = Path(__file__).resolve().parent.parent
if str(_MONOREPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_MONOREPO_ROOT))

from shared.anthropic_client import extract_text_from_message  # noqa: E402

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_MAX_WORKERS = 4  # llamadas Sonnet simultaneas maximas
_MAX_TOKENS_HTML = 8192

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
# Logo de la Universidad de Oviedo (assets/logo_uniovi.png)
# Helper replicado de generador_presentacion.py: ambos módulos son
# autocontenidos para evitar un import circular (generador_presentacion
# importa de generador_html).
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


from shared.text_utils import slugify as _slug

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
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
  <!-- CDN cargados una sola vez: los bloques individuales no deben incluirlos -->
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'DM Sans', sans-serif;
      background: #F7F5F0;
      color: #1A1A1A;
      line-height: 1.6;
    }

    /* ---- Page header (identidad institucional, igual que la presentación) ---- */
    .page-header {
      background: #003366;
      color: #FFFFFF;
      padding: 1.25rem 2rem;
      display: flex;
      align-items: center;
      gap: 1.5rem;
      border-bottom: 3px solid #C8A951;
      font-family: 'DM Sans', sans-serif;
    }
    .page-header h1 {
      font-size: 22px;
      font-weight: 500;
      margin-bottom: 0.25rem;
    }
    .page-header .subtitle {
      font-size: 14px;
      opacity: 0.75;
    }
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

    /* ---- CSS-only tab system (pill bar) ---- */
    .tab-inputs { display: none; }

    .tabs-wrapper {
      max-width: 860px;
      margin: 0 auto;
      padding: 2rem 1.5rem 4rem;
    }

    .tab-labels {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      background: #F0EEE9;
      border-radius: 12px;
      padding: 4px;
      margin-bottom: 2rem;
      border-bottom: none;
    }

    .tab-label {
      flex: 1;
      min-width: 0;
      cursor: pointer;
      padding: 8px;
      font-size: 13px;
      font-weight: 500;
      font-family: 'DM Sans', sans-serif;
      text-align: center;
      border-radius: 10px;
      color: #6B6860;
      background: transparent;
      border: none;
      transition: background 0.15s, color 0.15s;
    }
    .tab-label:hover { background: rgba(0,0,0,0.04); }

    .tab-panel { display: none; }

    /* Per-element active/show rules injected below */
<!--TAB_CSS-->

    /* ---- Page footer ---- */
    .page-footer {
      text-align: center;
      padding: 2rem;
      font-size: 0.8rem;
      color: #9A9890;
      border-top: 0.5px solid rgba(0,0,0,0.08);
      margin-top: 3rem;
    }
  </style>
</head>
<body>

<!-- Hidden radio inputs BEFORE the wrapper so ~ selector works -->
<!--TAB_INPUTS-->

<header class="page-header">
<!--LOGO-->
  <div>
    <h1><!--TITULO--></h1>
    <div class="subtitle">Material interactivo &mdash; Agente Presentaci&oacute;n</div>
  </div>
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

<script>
(function () {
  function initPanel(panel) {
    if (!panel || panel.dataset.initialized === "true") return;
    var slug = panel.dataset.slug;
    var initName = "initBloque_" + slug;

    function runInit() {
      if (typeof window[initName] === "function") {
        try {
          window[initName]();
        } catch (e) {
          console.error("Error en " + initName + ":", e);
        }
      } else {
        console.error(
          "No se encontró la función " + initName +
          " — el bloque de esta pestaña no puede inicializarse."
        );
      }
      panel.dataset.initialized = "true";
    }

    if (window.MathJax && window.MathJax.typesetPromise) {
      MathJax.typesetPromise([panel]).then(runInit).catch(runInit);
    } else {
      runInit();
    }
  }

  function setupTabs() {
    var inputs = document.querySelectorAll(".tab-inputs");
    inputs.forEach(function (input) {
      input.addEventListener("change", function () {
        if (!this.checked) return;
        var panelId = this.getAttribute("data-panel-id");
        initPanel(document.getElementById(panelId));
      });
    });
    var checked = document.querySelector(".tab-inputs:checked");
    if (checked) {
      initPanel(document.getElementById(checked.getAttribute("data-panel-id")));
    }
  }

  function boot() {
    if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
      MathJax.startup.promise.then(setupTabs);
    } else {
      setupTabs();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Parsing XML de visualización (mismo patrón que agente-contenido/classifier.py)
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
    nombre = elemento.get("nombre", "Sin nombre")
    user_msg = build_razonador_message(elemento, texto_original)

    response = client.messages.create(
        model=MODEL_SMART,
        max_tokens=1024,
        system=PROMPT_RAZONADOR_VISUALIZACION,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw, _ = extract_text_from_message(response)
    raw = raw.strip()
    visualizacion = _parse_visualizacion(raw, elemento)

    if verbose and visualizacion.get("VISUALIZABLE") != "NO":
        logger.debug("[%s] Patrón: %s", nombre, visualizacion["PATRON"])
        logger.debug("[%s] Eje X: %s", nombre, visualizacion["EJE_X"])
        logger.debug("[%s] Eje Y: %s", nombre, visualizacion["EJE_Y"])
        logger.debug("[%s] Justificación: %s", nombre, visualizacion["JUSTIFICACION"])
        if visualizacion.get("RANGO_VARIABLES"):
            logger.debug("[%s] Rangos: %s", nombre, visualizacion["RANGO_VARIABLES"])
        if visualizacion.get("ZONA_VALIDEZ"):
            logger.debug("[%s] Zona validez: %s", nombre, visualizacion["ZONA_VALIDEZ"])

    return visualizacion


# ---------------------------------------------------------------------------
# API call: generate one HTML block
# ---------------------------------------------------------------------------

def _is_valid_html(text: str) -> bool:
    """Return True if the text looks like an HTML fragment."""
    return bool(text) and "<" in text and ">" in text


def _parse_rango_variables(texto: str) -> dict[str, dict[str, float]]:
    """Parsea RANGO_VARIABLES del razonador a {variable: {min, max, default}}."""
    rangos: dict[str, dict[str, float]] = {}
    if not texto:
        return rangos
    for line in texto.strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        var_name, rest = line.split(":", 1)
        var_name = var_name.strip()
        rango: dict[str, float] = {}
        for match in re.finditer(
            r"(min|max|default)\s*=\s*([\d.]+)", rest, re.IGNORECASE
        ):
            rango[match.group(1).lower()] = float(match.group(2))
        if rango:
            rangos[var_name] = rango
    return rangos


def normalizar_nombre(nombre: str) -> str:
    """Convierte nombre de variable a forma normalizable para matching en IDs."""
    replacements = {
        "σ₀": "sigma0",
        "σ0": "sigma0",
        "σ_0": "sigma0",
        "σ_y": "sigmay",
        "σ_max": "sigmamax",
        "k_y": "ky",
        "c/ρ": "c_rho",
        "c/p": "c_rho",
        "ρ": "rho",
        "θ": "theta",
        "σ": "sigma",
        "ε": "epsilon",
    }
    nombre_norm = nombre.strip()
    for orig, repl in sorted(replacements.items(), key=lambda item: -len(item[0])):
        nombre_norm = nombre_norm.replace(orig, repl)
    nombre_norm = re.sub(r"[^a-zA-Z0-9_]", "", nombre_norm)
    if len(nombre_norm) == 1 and nombre_norm.isalpha():
        return nombre_norm
    return nombre_norm.lower()


def clave_variable(nombre: str) -> str:
    """Clave única en dicts; preserva d/D y otros símbolos de una letra."""
    return normalizar_nombre(nombre)


# ---------------------------------------------------------------------------
# Tabla de variables (contenido teórico — sección 5/6 del HTML generado)
# ---------------------------------------------------------------------------

_VARIABLE_RE = re.compile(
    r"\\(?:alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta"
    r"|iota|kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|varsigma|tau"
    r"|upsilon|phi|varphi|chi|psi|omega"
    r"|Alpha|Beta|Gamma|Delta|Epsilon|Zeta|Eta|Theta|Iota|Kappa|Lambda|Mu"
    r"|Nu|Xi|Pi|Rho|Sigma|Tau|Upsilon|Phi|Chi|Psi|Omega)"
    r"(?:_\{[^}]+\}|_[a-zA-Z0-9])?"
    r"|(?<![\\a-zA-Z])[a-zA-Z](?:_\{[^}]+\}|_[a-zA-Z0-9])?(?![a-zA-Z])"
)

_VARIABLE_TABLE_RE = re.compile(
    r"(\|[^\n]+\|\n\|[-|: ]+\|\n(?:\|[^\n]+\|\n?)+)",
    re.MULTILINE,
)

_DONDE_BLOQUE_RE = re.compile(r"(?:[Dd]onde|[Ss]iendo)\s*[:,]?\s*(.+?)(?:\n\n|\Z)", re.DOTALL)

_DONDE_ITEM_RE = re.compile(
    r"^\$?(\\[a-zA-Z]+(?:_\{[^}]+\}|_[a-zA-Z0-9])?|[a-zA-Z](?:_\{[^}]+\}|_[a-zA-Z0-9])?)\$?"
    r"\s*(?:es|representa|denota|=|:|—|-)\s+(.+)$"
)


def _extraer_variables_ecuacion(latex: str) -> list[str]:
    """Extrae los símbolos de variable distintos presentes en una expresión LaTeX.

    Preserva el orden de aparición y deduplica mediante clave_variable()
    (p. ej. \\sigma_y y sigma_y se consideran la misma variable).
    """
    variables: list[str] = []
    vistas: set[str] = set()
    for match in _VARIABLE_RE.finditer(latex):
        token = match.group(0)
        clave = clave_variable(token)
        if not clave or clave in vistas:
            continue
        vistas.add(clave)
        variables.append(token)
    return variables


def _extraer_descripciones_tablas(contexto: str) -> dict[str, dict[str, str]]:
    """Extrae descripciones de variables desde tablas Markdown (PASO A)."""
    resultado: dict[str, dict[str, str]] = {}
    for tabla_match in _VARIABLE_TABLE_RE.finditer(contexto):
        filas = [f for f in tabla_match.group(0).strip().splitlines() if f.strip()]
        if len(filas) < 2:
            continue
        cabecera = [c.strip().lower() for c in filas[0].strip("|").split("|")]
        idx_simbolo = idx_desc = idx_unidades = None
        for i, col in enumerate(cabecera):
            if idx_simbolo is None and any(k in col for k in ("símbolo", "simbolo", "variable")):
                idx_simbolo = i
            elif idx_desc is None and any(k in col for k in ("descripci", "significado", "nombre")):
                idx_desc = i
            elif idx_unidades is None and "unidad" in col:
                idx_unidades = i
        if idx_simbolo is None or idx_desc is None:
            continue
        for fila in filas[2:]:
            celdas = [c.strip() for c in fila.strip("|").split("|")]
            if len(celdas) <= max(idx_simbolo, idx_desc):
                continue
            simbolo = celdas[idx_simbolo].strip("$ *")
            descripcion = celdas[idx_desc].strip()
            unidades = (
                celdas[idx_unidades].strip()
                if idx_unidades is not None and idx_unidades < len(celdas)
                else ""
            )
            clave = clave_variable(simbolo)
            if clave and descripcion:
                resultado[clave] = {"descripcion": descripcion, "unidades": unidades}
    return resultado


def _extraer_descripciones_donde(contexto: str) -> dict[str, dict[str, str]]:
    """Extrae descripciones de variables de listas tipo 'Donde X es...' (PASO A)."""
    resultado: dict[str, dict[str, str]] = {}
    for bloque_match in _DONDE_BLOQUE_RE.finditer(contexto):
        bloque = bloque_match.group(1)
        for linea in re.split(r"[\n;]", bloque):
            linea = linea.strip().lstrip("-*•").strip()
            if not linea:
                continue
            for trozo in linea.split(","):
                trozo = trozo.strip()
                m = _DONDE_ITEM_RE.match(trozo)
                if not m:
                    continue
                clave = clave_variable(m.group(1))
                descripcion = m.group(2).strip().rstrip(".")
                if clave and descripcion and clave not in resultado:
                    resultado[clave] = {"descripcion": descripcion, "unidades": ""}
    return resultado


def _extraer_descripciones_markdown(contexto: str) -> dict[str, dict[str, str]]:
    """Combina las dos fuentes de descripción de variables del Markdown (PASO A)."""
    if not contexto:
        return {}
    resultado = _extraer_descripciones_donde(contexto)
    resultado.update(_extraer_descripciones_tablas(contexto))
    return resultado


def _describir_variables_haiku(
    latex: str,
    variables: list[str],
    contexto: str,
    client: anthropic.Anthropic,
) -> dict[str, dict[str, str]]:
    """Genera descripciones cortas para variables sin contexto (PASO B).

    Degrada graciosamente: si Haiku falla o la respuesta no es JSON válido,
    devuelve un dict vacío y el llamador marca esas variables como
    "Descripción no disponible".
    """
    if not variables:
        return {}
    try:
        response = client.messages.create(
            model=MODEL_FAST,
            max_tokens=512,
            system=PROMPT_DESCRIPCION_VARIABLES,
            messages=[{
                "role": "user",
                "content": build_descripcion_variables_message(latex, variables, contexto),
            }],
        )
        raw, _ = extract_text_from_message(response)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw).strip()
        data = json.loads(raw)
        resultado: dict[str, dict[str, str]] = {}
        for var, info in data.items():
            if not isinstance(info, dict):
                continue
            resultado[clave_variable(var)] = {
                "descripcion": str(info.get("descripcion", "")).strip(),
                "unidades": str(info.get("unidades", "")).strip(),
            }
        return resultado
    except Exception as exc:  # noqa: BLE001
        logger.warning("[VARIABLES] Descripción Haiku falló: %s", exc)
        return {}


def construir_tabla_variables(
    elemento: dict,
    client: anthropic.Anthropic,
) -> list[dict]:
    """Construye la tabla de variables de la ecuación (sección 6 del HTML).

    PASO A: busca descripciones en el Markdown circundante (tablas y listas
    tipo "Donde X es..."). PASO B: para las variables restantes, pide a
    Haiku una descripción corta usando la ecuación y el tema como contexto.

    Returns:
        Lista de dicts {simbolo, descripcion, unidades, generada}, en el
        mismo orden en que las variables aparecen en la ecuación.
    """
    latex = elemento.get("expresion", "")
    contexto = elemento.get("contexto", "")
    variables = _extraer_variables_ecuacion(latex)
    if not variables:
        return []

    descripciones_md = _extraer_descripciones_markdown(contexto)

    tabla: list[dict] = []
    pendientes: list[str] = []
    for var in variables:
        info = descripciones_md.get(clave_variable(var))
        if info:
            tabla.append({
                "simbolo": var,
                "descripcion": info["descripcion"],
                "unidades": info.get("unidades", "") or "?",
                "generada": False,
            })
        else:
            pendientes.append(var)
            tabla.append({"simbolo": var, "descripcion": "", "unidades": "", "generada": True})

    if pendientes:
        tema = elemento.get("seccion") or elemento.get("nombre", "")
        contexto_tema = f"{tema}\n\n{contexto}".strip()
        descripciones_haiku = _describir_variables_haiku(latex, pendientes, contexto_tema, client)
        for fila in tabla:
            if not fila["generada"]:
                continue
            info = descripciones_haiku.get(clave_variable(fila["simbolo"]))
            if info and info.get("descripcion"):
                fila["descripcion"] = info["descripcion"]
                fila["unidades"] = info.get("unidades") or "?"

    # Filtrar filas sin descripción útil (degradación de Haiku): son ruido
    # visual en el output. Si no queda ninguna fila, la lista vacía hace que
    # el generador omita la tabla por completo (regla de la sección 6 de
    # PROMPT_GENERADOR_HTML). Aplica a ambos outputs HTML, que comparten
    # esta función.
    return [
        fila for fila in tabla
        if fila.get("descripcion")
        and fila["descripcion"] != "Descripción no disponible"
    ]


_ALIASES_VARIABLE: dict[str, tuple[str, ...]] = {
    "n": ("numero", "espiras", "espira", "turns", "coils", "activas"),
    "N": ("numero", "espiras", "espira", "turns", "coils", "activas"),
    "d": ("alambre", "wire", "varilla", "grosor", "diametro_alambre"),
    "D": ("diametro_medio", "medio", "mean", "coil", "espira_exterior"),
    "g": ("cizalla", "shear", "modulog", "modulo_g"),
    "G": ("cizalla", "shear", "modulog", "modulo_g"),
    "e": ("elastico", "young", "elastic", "moduloe", "modulo_e"),
    "E": ("elastico", "young", "elastic", "moduloe", "modulo_e"),
    "k": ("rigidez", "stiffness", "constante"),
    "t": ("espesor", "thickness", "temperatura"),
    "l": ("longitud", "length"),
    "r": ("radio", "radius"),
    "c": ("relacion", "indice", "compliance"),
}


def _parse_parametros_slider(texto: str) -> list[str]:
    """Parsea la lista de parámetros con slider del razonador."""
    if not texto:
        return []
    return [p.strip() for p in re.split(r"[,;]", texto) if p.strip()]


def _filtrar_rangos_para_sliders(
    rangos: dict[str, dict[str, float]],
    parametros_slider: list[str],
) -> dict[str, dict[str, float]]:
    """Conserva solo rangos de variables que tienen slider (no ejes X/Y)."""
    if not parametros_slider:
        return rangos
    param_norms = {clave_variable(p) for p in parametros_slider}
    return {
        k: v for k, v in rangos.items() if clave_variable(k) in param_norms
    }


def _format_rango_val(val: float) -> str:
    """Formatea un valor numérico de rango para atributos HTML."""
    return str(int(val)) if val == int(val) else str(val)


def _ajustar_atributos_range(tag: str, rango: dict[str, float]) -> str:
    """Sustituye o añade min, max y value en un tag input[type=range]."""
    attrs = {
        "min": rango.get("min"),
        "max": rango.get("max"),
        "value": rango.get("default"),
    }
    for attr, val in attrs.items():
        if val is None:
            continue
        val_s = _format_rango_val(val)
        if re.search(rf"\b{attr}\s*=", tag, re.IGNORECASE):
            tag = re.sub(
                rf'\b{attr}\s*=\s*["\'][^"\']*["\']',
                f'{attr}="{val_s}"',
                tag,
                flags=re.IGNORECASE,
            )
            tag = re.sub(
                rf"\b{attr}\s*=\s*[\d.+-]+",
                f'{attr}="{val_s}"',
                tag,
                flags=re.IGNORECASE,
            )
        else:
            insert = f' {attr}="{val_s}"'
            if tag.rstrip().endswith("/>"):
                tag = tag.rstrip()[:-2] + insert + " />"
            else:
                tag = tag.rstrip()[:-1] + insert + ">"
    return tag


def _id_coincide_variable(id_attr: str, var_key: str) -> bool:
    """True si el id del input corresponde a la variable."""
    id_norm = re.sub(r"[^a-z0-9_]", "_", id_attr.lower())
    id_compact = re.sub(r"[^a-z0-9]", "", id_attr.lower())
    var_lower = var_key.lower()
    if len(var_lower) <= 2:
        if re.search(rf"(?:^|_){re.escape(var_lower)}(?:_|$)", id_norm):
            return True
    elif var_lower in id_compact:
        return True
    for alias in _ALIASES_VARIABLE.get(var_key, ()):
        if alias in id_compact:
            return True
    return False


_DATA_VAR_RE = re.compile(
    r'\bdata-var\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE
)

_RANGE_INPUT_RE = re.compile(
    r"<input\b([^>]*?\btype\s*=\s*[\"']range[\"'][^>]*?)/?>",
    re.IGNORECASE,
)


def _variable_desde_input(
    inner: str, rangos_por_clave: dict[str, dict[str, float]]
) -> str | None:
    """Empareja un input range con la variable del razonador, si es posible."""
    data_match = _DATA_VAR_RE.search(inner)
    if data_match:
        var_key = clave_variable(data_match.group(1))
        if var_key in rangos_por_clave:
            return var_key

    for attr in ("id", "name"):
        attr_match = re.search(
            rf'\b{attr}\s*=\s*["\']([^"\']+)["\']', inner, re.IGNORECASE
        )
        if not attr_match:
            continue
        attr_val = attr_match.group(1)
        for var_key in sorted(rangos_por_clave, key=len, reverse=True):
            if _id_coincide_variable(attr_val, var_key):
                return var_key
    return None


def aplicar_rangos(
    html_bloque: str,
    rangos: dict[str, dict[str, float]],
    verbose: bool = False,
    parametros_slider: str = "",
) -> str:
    """Corrige min/max/value de sliders según RANGO_VARIABLES del razonador."""
    if not rangos:
        return html_bloque

    params_slider = _parse_parametros_slider(parametros_slider)
    rangos_efectivos = _filtrar_rangos_para_sliders(rangos, params_slider)

    rangos_por_clave = {clave_variable(k): v for k, v in rangos_efectivos.items()}
    orig_por_clave = {clave_variable(k): k for k in rangos_efectivos}
    matched: set[str] = set()

    matches = list(_RANGE_INPUT_RE.finditer(html_bloque))
    if not matches:
        if verbose:
            for var_key, nombre_orig in orig_por_clave.items():
                logger.warning(
                    '[RANGOS] Variable "%s" no encontrada en el HTML — slider no corregido',
                    nombre_orig,
                )
        return html_bloque

    assignments: list[tuple[re.Match[str], str | None]] = []
    for match in matches:
        var_key = _variable_desde_input(match.group(1), rangos_por_clave)
        if var_key:
            matched.add(var_key)
        assignments.append((match, var_key))

    if params_slider:
        pending_vars = [
            clave_variable(p)
            for p in params_slider
            if clave_variable(p) in rangos_por_clave
            and clave_variable(p) not in matched
        ]
        pending_idxs = [i for i, (_, var_key) in enumerate(assignments) if var_key is None]
        for idx, var_key in zip(pending_idxs, pending_vars):
            assignments[idx] = (assignments[idx][0], var_key)
            matched.add(var_key)

    html_corregido = html_bloque
    for match, var_key in reversed(assignments):
        if not var_key:
            continue
        new_tag = _ajustar_atributos_range(
            f"<input{match.group(1)}>", rangos_por_clave[var_key]
        )
        html_corregido = (
            html_corregido[: match.start()]
            + new_tag
            + html_corregido[match.end() :]
        )

    if verbose:
        for var_key, nombre_orig in orig_por_clave.items():
            if var_key not in matched:
                logger.warning(
                    '[RANGOS] Variable "%s" no encontrada en el HTML — slider no corregido',
                    nombre_orig,
                )

    return html_corregido


def validar_rangos(
    html_bloque: str,
    rangos_esperados: dict[str, dict[str, float]],
    nombre: str = "",
    parametros_slider: str = "",
) -> None:
    """Comprueba que los defaults del razonador aparecen en el HTML generado."""
    params_slider = _parse_parametros_slider(parametros_slider)
    rangos_esperados = _filtrar_rangos_para_sliders(
        rangos_esperados, params_slider
    )
    prefijo = f"[ADVERTENCIA] {nombre}: " if nombre else "[ADVERTENCIA] "
    for variable, rango in rangos_esperados.items():
        default = rango.get("default")
        if default is None:
            continue
        default_str = (
            str(int(default)) if default == int(default) else str(default)
        )
        patron = rf'value=["\']?{re.escape(default_str)}["\']?'
        if not re.search(patron, html_bloque):
            logger.warning(
                "%sRango incorrecto para %s: esperado default=%s",
                prefijo,
                variable,
                default_str,
            )


_DOMLOADED_RE = re.compile(
    r"addEventListener\(\s*['\"`]DOMContentLoaded['\"`]", re.IGNORECASE
)


def _ultimo_script_cerrado(bloque: str) -> bool:
    """True si el último <script> del bloque tiene su </script> (no cortado a medias)."""
    low = (bloque or "").lower()
    last_open = low.rfind("<script")
    if last_open == -1:
        return False
    last_close = low.rfind("</script>")
    return last_close != -1 and last_close > last_open


def validar_bloque_html(
    bloque: str, slug: str, requiere_autoarranque: bool = True
) -> tuple[bool, str]:
    """Valida que el bloque incluye initBloque global, su arranque y el cierre.

    Comprueba:
      1. La definición global ``window['initBloque_{slug}'] = ...`` existe
         (no basta con que el nombre aparezca en cualquier parte del texto).
      2. Si ``requiere_autoarranque`` es True: existe la llamada de arranque
         (un listener DOMContentLoaded y la invocación
         ``window['initBloque_{slug}']()``). Si es False (presentación
         completa), esta condición se omite — el contenedor invoca
         ``initBloque_{slug}()`` externamente vía IntersectionObserver y un
         DOMContentLoaded propio sería innecesario.
      3. El último ``<script>`` del bloque está cerrado con ``</script>`` (no cortado
         a medias). Puede haber markup (p. ej. ``</div>``) después del script.

    Las comillas del acceso a window pueden ser simples, dobles o backticks
    (Sonnet alterna entre las tres formas — las tres son JS válido).

    Returns:
        (es_valido, motivo): motivo es "" si el bloque es válido; si no,
        describe exactamente qué condición falló (se muestra en el
        placeholder de error).
    """
    slug_re = re.escape(slug)
    motivos: list[str] = []

    if not re.search(
        rf"window\[\s*['\"`]initBloque_{slug_re}['\"`]\s*\]\s*=", bloque
    ):
        motivos.append(
            f"falta la definición global window['initBloque_{slug}']"
        )

    if requiere_autoarranque:
        tiene_listener = bool(_DOMLOADED_RE.search(bloque))
        tiene_llamada = bool(
            re.search(
                rf"window\[\s*['\"`]initBloque_{slug_re}['\"`]\s*\]\s*\(", bloque
            )
        )
        if not (tiene_listener and tiene_llamada):
            motivos.append(
                f"falta la llamada DOMContentLoaded a initBloque_{slug}"
            )

    if not _ultimo_script_cerrado(bloque):
        motivos.append("script truncado (sin cierre </script>)")

    return (not motivos, "; ".join(motivos))


_GRAFICA_KEYWORDS = (
    "gráfic", "grafic", "chart", "diagrama de fase", "trazar", "plot",
    "frente a", " versus ", " vs ",
    "tensión-deformación", "tension-deformacion", "σ-ε", "sigma-epsilon",
)

_CURVA_KEYWORDS = (
    "curva de", "curva σ", "curva tensión", "curva tension",
    "curva sn", "curva p-v", "deformación", "deformacion",
)

_EXCLUYE_GRAFICA_PHRASES = (
    "sin gráfica", "sin grafica", "sin chart", "sin canvas", "sin curva",
    "no chart", "solo svg", "sin canvas",
)

_MECANISMO_KEYWORDS = (
    "actuador", "cilindro", "émbolo", "embolo", "vástago", "vastago",
    "mecanismo", "svg", "botón", "boton", "botones", "avanzar", "retroceder",
    "animación", "animacion", "pistón", "piston", "válvula de corredera",
    "valvula de corredera", "doble efecto", "simple efecto",
)

_JS_CORRUPTO_RE = re.compile(
    r"tension\s*:\s*0\.4\.4|tension\s*:\s*0\.0\.4"
)


def instruccion_excluye_grafica(instruccion: str) -> bool:
    """True si el profesor pide explícitamente evitar Chart.js / curvas."""
    inst = (instruccion or "").lower()
    return any(p in inst for p in _EXCLUYE_GRAFICA_PHRASES)


def instruccion_es_mecanismo_svg(instruccion: str) -> bool:
    """True si la petición es animación SVG de mecanismo, no gráfica Chart.js."""
    inst = (instruccion or "").lower()
    if instruccion_excluye_grafica(inst):
        return True
    if not any(k in inst for k in _MECANISMO_KEYWORDS):
        return False
    pide_curva = any(k in inst for k in _CURVA_KEYWORDS) or any(
        k in inst for k in ("chart.js", "chartjs", "new chart")
    )
    return not pide_curva


def instruccion_pide_grafica_curva_taller(instruccion: str) -> bool:
    """True si la instrucción requiere validación Chart.js (curvas, diagramas)."""
    if instruccion_es_mecanismo_svg(instruccion):
        return False
    inst = (instruccion or "").lower()
    if any(k in inst for k in _GRAFICA_KEYWORDS):
        return True
    if any(k in inst for k in _CURVA_KEYWORDS):
        return True
    if "curva" in inst and not instruccion_excluye_grafica(inst):
        return True
    if "representa" in inst and any(
        w in inst for w in ("curva", "gráfic", "grafic", "tensión", "tension", "diagrama")
    ):
        return True
    return False


def validar_grafica_taller(html: str, instruccion: str = "") -> tuple[bool, str]:
    """Comprueba canvas/Chart.js solo cuando la instrucción pide gráfica de curvas."""
    if _JS_CORRUPTO_RE.search(html):
        return False, "sintaxis JS inválida en tension (valor corrupto)"

    tiene_canvas = bool(re.search(r"<canvas\b", html, re.IGNORECASE))
    tiene_chart = "new Chart" in html
    tiene_svg = bool(re.search(r"<svg\b", html, re.IGNORECASE))
    pide_grafica = instruccion_pide_grafica_curva_taller(instruccion)
    es_mecanismo = instruccion_es_mecanismo_svg(instruccion)

    if es_mecanismo:
        if tiene_canvas and not tiene_chart:
            return False, "falta new Chart(...) — el script no inicializa la gráfica"
        if not tiene_svg:
            return False, "falta <svg> para la animación del mecanismo"
        return True, ""

    if pide_grafica or tiene_canvas:
        if not tiene_canvas:
            return False, "falta <canvas> para la gráfica pedida"
        if not tiene_chart:
            return False, "falta new Chart(...) — el script no inicializa la gráfica"
        inst = (instruccion or "").lower()
        es_curva = (
            re.search(r"type\s*:\s*['\"]line['\"]", html) is not None
            or any(w in inst for w in ("curva", "tensión", "tension", "deformación", "deformacion"))
        )
        if es_curva and not re.search(r"for\s*\(", html):
            return False, (
                "falta bucle for de muestreo — la curva debe evaluarse con 80+ puntos"
            )
        ok_cal, motivo_cal = evaluar_calidad_curva_html(html)
        if not ok_cal:
            return False, motivo_cal
    return True, ""


_LITERAL_XY_RE = re.compile(
    r"\{\s*x\s*:\s*[-+]?[\d.eE]+\s*,\s*y\s*:\s*[-+]?[\d.eE]+\s*\}"
)
_PUSH_XY_RE = re.compile(
    r"\.push\s*\(\s*\{\s*x\s*:\s*([-+]?[\d.eE]+)\s*,\s*y\s*:\s*([-+]?[\d.eE]+)\s*\}"
)
_DATA_ARRAY_BLOCK_RE = re.compile(
    r"const\s+data_\w+\s*=\s*\[\s*\];(.*?)(?=const\s+data_\w+\s*=\s*\[\s*\];|const\s+chart\s*=|new\s+Chart)",
    re.DOTALL | re.IGNORECASE,
)


def _extraer_series_push(html: str) -> list[list[tuple[float, float]]]:
    """Extrae series de puntos {x,y} por bloque data_* en el JS generado."""
    series: list[list[tuple[float, float]]] = []
    for block in _DATA_ARRAY_BLOCK_RE.findall(html or ""):
        pts = [
            (float(m.group(1)), float(m.group(2)))
            for m in _PUSH_XY_RE.finditer(block)
        ]
        if pts:
            series.append(pts)
    if not series:
        pts = [
            (float(m.group(1)), float(m.group(2)))
            for m in _PUSH_XY_RE.finditer(html or "")
        ]
        if pts:
            series.append(pts)
    return series


def detectar_saltos_curva_puntos(
    puntos: list[tuple[float, float]],
) -> tuple[bool, str]:
    """Detecta saltos verticales o discontinuidades bruscas entre puntos consecutivos."""
    if len(puntos) < 3:
        return True, ""

    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    x_span = max(xs) - min(xs) or 1.0
    y_span = max(ys) - min(ys) or 1.0

    for i in range(1, len(puntos)):
        x0, y0 = puntos[i - 1]
        x1, y1 = puntos[i]
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)

        if dx <= 0.08 * x_span and dy >= 0.18 * y_span:
            return False, (
                f"salto vertical en la curva entre x={x0:.3g} y x={x1:.3g} "
                f"(Δy={dy:.0f}, Δx={dx:.3g})"
            )

        if dx > 0 and dy > max(80.0, 0.28 * y_span):
            slope = dy / dx
            if i >= 2:
                x_prev, y_prev = puntos[i - 2]
                dx_prev = abs(x0 - x_prev) or 1e-9
                dy_prev = abs(y0 - y_prev)
                slope_prev = dy_prev / dx_prev
                if slope > 6 * max(slope_prev, 0.5) and dy > 0.12 * y_span:
                    return False, (
                        f"discontinuidad brusca cerca de x={x1:.3g} "
                        f"(pendiente local {slope:.0f} vs {slope_prev:.0f})"
                    )
    return True, ""


def evaluar_coherencia_tramos_curva(html: str) -> tuple[bool, str]:
    """Detecta incoherencias genéricas en curvas por tramos (cualquier fenómeno)."""
    src = html or ""
    if "new Chart" not in src and "<canvas" not in src.lower():
        return True, ""

    # Solo decaimientos del tipo y_a - K·Δ^p con exponente < 1 (tangente vertical en frontera).
    # No aplica a endurecimiento plástico (t^0.65 con t normalizado en [0,1]).
    if re.search(r"-\s*(?:\d+\.?\d*|[A-Za-z_][\w.]*)\s*\*\s*Math\.pow\s*\(", src):
        for m in re.finditer(
            r"-\s*\w+\s*\*\s*Math\.pow\s*\([^)]*,\s*(?:p\.|params\.)?(\w+)",
            src,
        ):
            exp_name = m.group(1)
            exp_m = re.search(
                rf"(?:\b{re.escape(exp_name)}\s*[:=]\s*)([\d.]+)", src
            )
            if exp_m:
                try:
                    if float(exp_m.group(1)) < 1.0:
                        return False, (
                            "exponente <1 en decaimiento (y_a - K·Δx^p) puede producir "
                            "salto o tangente vertical — usar interpolación con exponente ≥1 "
                            "o fórmula normalizada entre fronteras"
                        )
                except ValueError:
                    continue

    pts = [
        (float(m.group(1)), float(m.group(2)))
        for m in _PUSH_XY_RE.finditer(src)
    ]
    if pts:
        ok, motivo = detectar_saltos_curva_puntos(pts)
        if not ok:
            return False, motivo

    return True, ""


def evaluar_continuidad_curva_html(html: str) -> tuple[bool, str]:
    """Comprueba continuidad visual de cada serie muestreada con .push({x,y})."""
    ok_tramos, motivo_tramos = evaluar_coherencia_tramos_curva(html)
    if not ok_tramos:
        return False, motivo_tramos

    for idx, serie in enumerate(_extraer_series_push(html), start=1):
        ok, motivo = detectar_saltos_curva_puntos(serie)
        if not ok:
            pref = f"serie {idx}" if len(_extraer_series_push(html)) > 1 else "la curva"
            return False, f"{pref}: {motivo}"
    return True, ""


def _tiene_muestreo_denso(html: str) -> bool:
    """True si el JS evalúa la curva en un bucle con muchos puntos (no literales sueltos)."""
    src = html or ""
    if src.count(".push(") >= 40:
        return True
    if not re.search(r"for\s*\(", src) or ".push(" not in src:
        return False
    m = re.search(r"\bN\s*[:=]\s*(\d+)", src)
    if m and int(m.group(1)) >= 80:
        return True
    if re.search(r"<=\s*P\.N|/\s*P\.N", src):
        return True
    if re.search(r"for\s*\([^)]*<=\s*(?:1[0-9]|[2-9]\d)\d", src):
        return True
    return False


def evaluar_calidad_curva_html(html: str) -> tuple[bool, str]:
    """Heurísticas automáticas sobre el JS generado para curvas Chart.js."""
    muestreo_denso = _tiene_muestreo_denso(html)

    if re.search(r"tension\s*:\s*0(\s*[,}])", html) and not muestreo_denso:
        return False, "tension: 0 con pocos puntos — evaluar fórmula en bucle o usar tension: 0.4"

    literales = _LITERAL_XY_RE.findall(html)
    tiene_bucle = bool(re.search(r"for\s*\(", html))
    tiene_push = ".push(" in html

    if literales and len(literales) < 20 and not tiene_bucle and not tiene_push:
        return False, (
            f"solo {len(literales)} puntos literales estáticos — evaluar fórmula en bucle"
        )

    if tiene_bucle:
        pushes = html.count(".push(")
        if pushes < 1 and "data:" in html and "datasets" in html:
            return False, "hay bucle pero no se acumulan puntos con .push()"

    if re.search(r"(?:return|=|,\s*)NaN\b", html) or re.search(
        r"(?:return|=|,\s*)Infinity\b", html
    ):
        return False, "el script contiene NaN o Infinity — revisar fórmulas"

    ok_cont, motivo_cont = evaluar_continuidad_curva_html(html)
    if not ok_cont:
        return False, motivo_cont

    return True, ""


def _bloque_placeholder(slug: str, nombre: str, motivo: str = "") -> str:
    """HTML de reserva cuando Sonnet devuelve un bloque truncado o inválido."""
    nombre_esc = nombre.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    motivo_esc = motivo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    detalle = (
        f'<p style="font-size:12px;line-height:1.5;color:#9A9890;'
        f'margin-top:0.5rem;">Motivo: {motivo_esc}</p>'
        if motivo
        else ""
    )
    return (
        f'<div id="bloque_{slug}_card" style="background:#FFFFFF;'
        f"border:0.5px solid rgba(0,0,0,0.08);border-radius:14px;"
        f'padding:1.75rem 2rem;font-family:\'DM Sans\',sans-serif;">'
        f'<h2 style="font-family:\'Playfair Display\',serif;font-size:24px;'
        f'font-weight:600;color:#1A1A1A;margin-bottom:0.75rem;">{nombre_esc}</h2>'
        f'<p style="font-size:14px;line-height:1.65;color:#6B6860;">'
        "No se pudo generar la visualización para este elemento. "
        "Prueba a seleccionar menos elementos simultáneamente."
        "</p>"
        f"{detalle}"
        f"<script>window['initBloque_{slug}'] = function() {{}};</script>"
        "</div>"
    )


def _generar_bloque(
    elemento: dict,
    idx: int,
    verbose: bool = False,
    texto_original: str | None = None,
    requiere_autoarranque: bool = True,
    visualizacion: dict | None = None,
) -> tuple[int, str]:
    """Call Sonnet to generate the interactive HTML panel for one element.

    Paso 1: razonador de visualización (patrón adaptativo) — se omite si
        `visualizacion` se pasa directamente (patrón ya elegido por el profesor).
    Paso 2: generador HTML — siempre genera si el elemento fue seleccionado.

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
        verbose: If True, print pattern and justification to stdout.
        requiere_autoarranque: True (HTML por pestañas) exige que el bloque
            incluya su propio listener DOMContentLoaded que invoque
            initBloque_{slug}(). False (presentación completa) omite esa
            exigencia: el contenedor invoca initBloque_{slug}() vía
            IntersectionObserver al entrar en el viewport.
        visualizacion: Si se proporciona, se usa directamente sin llamar al
            razonador. Útil cuando el patrón ya ha sido elegido previamente
            (p. ej., persistido en BD por el profesor).

    Returns:
        (idx, html_block) where html_block is the Sonnet-generated HTML
        fragment or an error panel div.
    """
    nombre = elemento.get("nombre", f"Elemento {idx + 1}")
    slug = _slug(nombre)
    advertencia = elemento.get("advertencia")

    if verbose and advertencia:
        logger.debug(
            '[GENERADOR] Elemento "%s" generado con advertencia: %s',
            nombre,
            advertencia,
        )

    last_exc: Exception | None = None
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=float(REQUEST_TIMEOUT_SECONDS),
    )

    if visualizacion is None:
        try:
            visualizacion = _razonar_visualizacion(
                elemento, client, verbose=verbose, texto_original=texto_original
            )
        except Exception as exc:  # noqa: BLE001
            if verbose:
                logger.warning("[%s] Razonador falló: %s — usando CURVA_SIMPLE", nombre, exc)
            visualizacion = _fallback_visualizacion(elemento)

        if visualizacion.get("VISUALIZABLE") == "NO":
            visualizacion = _fallback_visualizacion(elemento)

    rangos_raw = visualizacion.get("RANGO_VARIABLES", "")
    if verbose:
        logger.debug(
            "[GENERADOR] Rangos para %s: %s",
            nombre,
            rangos_raw or "NO ENCONTRADO",
        )

    tabla_variables = construir_tabla_variables(elemento, client)
    user_msg = build_generador_message(
        elemento, visualizacion, slug, tabla_variables,
        requiere_autoarranque=requiere_autoarranque,
    )
    rangos_esperados = _parse_rango_variables(rangos_raw)
    parametros_slider = visualizacion.get("PARAMETROS_SLIDER", "")

    bloque_incompleto = False
    motivo_fallo = ""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            # Reintento correctivo: repetir el mismo mensaje produce a menudo
            # el mismo fallo. Indicar a Sonnet qué se rechazó y qué se espera.
            mensaje = user_msg
            if attempt and motivo_fallo:
                if requiere_autoarranque:
                    mensaje = (
                        f"{user_msg}\n\n"
                        f"CORRECCIÓN OBLIGATORIA — tu respuesta anterior fue "
                        f"rechazada por: {motivo_fallo}.\n"
                        f"El bloque DEBE contener, en el nivel superior del "
                        f"<script> y con comillas simples:\n"
                        f"  window['initBloque_{slug}'] = function() {{ ... }};\n"
                        f"y al final del <script>:\n"
                        f"  document.addEventListener('DOMContentLoaded', "
                        f"function() {{\n"
                        f"    try {{ window['initBloque_{slug}'](); }}\n"
                        f"    catch(e) {{ console.error('Error en "
                        f"initBloque_{slug}:', e); }}\n"
                        f"  }});"
                    )
                else:
                    mensaje = (
                        f"{user_msg}\n\n"
                        f"CORRECCIÓN OBLIGATORIA — tu respuesta anterior fue "
                        f"rechazada por: {motivo_fallo}.\n"
                        f"El bloque DEBE contener, en el nivel superior del "
                        f"<script> y con comillas simples:\n"
                        f"  window['initBloque_{slug}'] = function() {{ ... }};\n"
                        f"NO añadas ningún listener DOMContentLoaded — el "
                        f"contenedor de la presentación invoca "
                        f"window['initBloque_{slug}']() automáticamente "
                        f"cuando el bloque entra en el viewport."
                    )
            response = client.messages.create(
                model=MODEL_SMART,
                max_tokens=_MAX_TOKENS_HTML,
                system=PROMPT_GENERADOR_HTML,
                messages=[{"role": "user", "content": mensaje}],
            )
            raw, _ = extract_text_from_message(response)
            raw = raw.strip()

            # Strip accidental backtick code fences despite prompt instructions
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw).strip()

            if getattr(response, "stop_reason", None) == "max_tokens":
                bloque_incompleto = True
                motivo_fallo = "respuesta truncada por límite de tokens (max_tokens)"
                logger.warning(
                    "[GENERADOR] Respuesta truncada (max_tokens) para slug=%r — intento %s",
                    slug,
                    attempt + 1,
                )
                last_exc = ValueError("Respuesta truncada por límite de tokens")
                continue

            if _is_valid_html(raw):
                if rangos_esperados:
                    raw = aplicar_rangos(
                        raw,
                        rangos_esperados,
                        verbose=verbose,
                        parametros_slider=parametros_slider,
                    )
                bloque_valido, motivo_validacion = validar_bloque_html(
                    raw, slug, requiere_autoarranque=requiere_autoarranque
                )
                if bloque_valido:
                    if rangos_esperados:
                        validar_rangos(
                            raw,
                            rangos_esperados,
                            nombre,
                            parametros_slider=parametros_slider,
                        )
                    return idx, raw

                bloque_incompleto = True
                motivo_fallo = motivo_validacion
                logger.warning(
                    "[GENERADOR] Bloque incompleto para slug=%r (%s) — intento %s",
                    slug,
                    motivo_validacion,
                    attempt + 1,
                )
                last_exc = ValueError(
                    f"Bloque HTML inválido para initBloque_{slug}: "
                    f"{motivo_validacion}"
                )
                continue

            last_exc = ValueError(
                f"Intento {attempt + 1}: respuesta sin HTML valido "
                f"(primeros 120 chars: {raw[:120]!r})"
            )

        except anthropic.RateLimitError as exc:
            # El límite de output tokens/min se agota con varios bloques en
            # paralelo; reintentar de inmediato vuelve a chocar con él.
            last_exc = exc
            if attempt < _MAX_RETRIES:
                espera = 30 * (attempt + 1)
                logger.warning(
                    "[GENERADOR] Rate limit (429) para slug=%r — esperando "
                    "%s s antes del intento %s",
                    slug,
                    espera,
                    attempt + 2,
                )
                time.sleep(espera)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    if bloque_incompleto:
        return idx, _bloque_placeholder(slug, nombre, motivo_fallo)

    # All retries exhausted — return visible error panel
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


def generar_bloque_con_visualizacion(
    elemento: dict,
    visualizacion: dict,
    requiere_autoarranque: bool = True,
) -> str:
    """Genera el bloque HTML para un elemento usando un `visualizacion` dict ya construido.

    A diferencia del pipeline completo (razonador → generador), esta función recibe
    directamente el dict de visualización — útil cuando el patrón fue elegido
    previamente por el profesor y persistido en BD. El bucle de reintentos,
    `aplicar_rangos` y `validar_bloque_html` se ejecutan igual que en `_generar_bloque`.

    Args:
        elemento: Dict del elemento con claves nombre, expresion, contexto.
        visualizacion: Dict con PATRON, PARAMETROS_SLIDER, RANGO_VARIABLES, etc.
            Debe contener al menos {'VISUALIZABLE': 'SI', 'PATRON': '<PATRON>'}.
        requiere_autoarranque: Ver `_generar_bloque`.

    Returns:
        HTML del bloque generado, o placeholder de error si todos los intentos fallan.
    """
    _, html = _generar_bloque(
        elemento, 0,
        requiere_autoarranque=requiere_autoarranque,
        visualizacion=visualizacion,
    )
    return html


# ---------------------------------------------------------------------------
# Assembly: wrap blocks in the HTML page container
# ---------------------------------------------------------------------------

_PREVIEW_TALLER_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Preview</title>
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; padding: 1rem; background: #ffffff; color: #1a1a1a; }
    canvas { max-width: 100%; }
    div:has(> canvas) { min-height: 320px; position: relative; }
  </style>
</head>
<body>
<!--FRAGMENT-->
<script>
(function () {
  function runInits() {
    Object.getOwnPropertyNames(window).forEach(function (name) {
      if (name.indexOf("initBloque_") !== 0) return;
      if (typeof window[name] !== "function") return;
      try {
        window[name]();
      } catch (e) {
        console.error("Error en " + name + ":", e);
      }
    });
  }
  function boot() {
    if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
      MathJax.startup.promise.then(runInits).catch(runInits);
    } else {
      runInits();
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
</script>
</body>
</html>
"""


_TENSION_CORRUPTO_RE = re.compile(r"(\btension\s*:\s*)0\.4\.4")
_TENSION_CERO_RE = re.compile(r"(\btension\s*:\s*)0(\s*[,}])")


def sanitizar_chartjs_html(html: str) -> str:
    """Repara tension corrupta por post-procesado y sustituye tension: 0 explícito."""
    html = _TENSION_CORRUPTO_RE.sub(r"\g<1>0.4", html)
    if not _tiene_muestreo_denso(html):
        html = _TENSION_CERO_RE.sub(r"\g<1>0.4\2", html)
    return html


_SLUG_INIT_RE = re.compile(
    r"window\[\s*['\"`]initBloque_([^'\"`]+)['\"`]\s*\]\s*="
)


def extraer_slug_desde_html(html: str) -> str | None:
    """Obtiene el slug del bloque a partir de initBloque_{slug} en el HTML."""
    m = _SLUG_INIT_RE.search(html or "")
    return m.group(1) if m else None


def envolver_preview_taller(html_fragment: str) -> str:
    """Envoltorio mínimo para la vista previa del taller (sin formato institucional)."""
    fragmento = sanitizar_chartjs_html(html_fragment)
    return _PREVIEW_TALLER_TEMPLATE.replace("<!--FRAGMENT-->", fragmento)


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
            f' id="{input_id}" data-panel-id="{panel_id}"'
            f' data-slug="{slug}"{checked}>'
        )
        labels_parts.append(
            f'    <label class="tab-label" for="{input_id}">{nombre_esc}</label>'
        )
        panels_parts.append(
            f'  <section class="tab-panel" id="{panel_id}"'
            f' data-slug="{slug}" data-initialized="false">\n'
            f"{html_block}\n"
            f"  </section>"
        )

        # Active tab label (pill style)
        css_parts.append(
            f'    #{input_id}:checked ~ .tabs-wrapper'
            f' .tab-label[for="{input_id}"] {{'
            f" color: #1A1A1A; background: #FFFFFF;"
            f" border: 0.5px solid rgba(0,0,0,0.08); border-radius: 10px; }}"
        )
        # Show matching panel
        css_parts.append(
            f"    #{input_id}:checked ~ .tabs-wrapper #{panel_id}"
            f" {{ display: block; }}"
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

    html = _HTML_TEMPLATE
    html = html.replace("<!--TITULO-->", titulo_esc)
    html = html.replace("<!--LOGO-->", logo_html)
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
    titulo_tema: str = "Material interactivo",
    verbose: bool = True,
    texto_original: str | None = None,
) -> str:
    """Generate a self-contained interactive HTML page from selected elements.

    Por cada elemento: primero razona el patrón de visualización, luego
    genera el HTML adaptado. Las llamadas se ejecutan en paralelo — hasta
    _MAX_WORKERS concurrent requests — preservando el orden original.

    The HTML container (head, tab navigation, page header, footer) is built
    from a fixed Python template. MathJax and Chart.js CDNs appear once in
    <head>; Sonnet-generated blocks must not include them (enforced via the
    IMPORTANTE section of PROMPT_GENERADOR_HTML).

    Args:
        elementos: List of element dicts. Each must have: nombre, expresion,
                   contexto. Optional: variables_entrada (list[dict] with
                   nombre, unidades, min, max), variable_salida (dict with
                   nombre, unidades). Missing optional fields use safe defaults.
        titulo_tema: Text shown in the browser tab and the blue page header.
        verbose: If True, print chosen pattern and justification per element.
        texto_original: Optional text from professor's PDF/PPTX for razonador.

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
            executor.submit(_generar_bloque, el, i, verbose, texto_original): i
            for i, el in enumerate(elementos)
        }
        for future in as_completed(futures):
            resultados.append(future.result())

    resultados.sort(key=lambda t: t[0])

    bloques: list[tuple[str, str]] = [
        (elementos[i].get("nombre", f"Elemento {i + 1}"), html_block)
        for i, html_block in resultados
    ]

    return _construir_pagina(bloques, titulo_tema)
