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

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    MODEL_SMART,
    REQUEST_TIMEOUT_SECONDS,
)
from prompts import (
    PROMPT_GENERADOR_HTML,
    PROMPT_RAZONADOR_VISUALIZACION,
    build_generador_message,
    build_razonador_message,
)


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
})


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

    /* ---- Page header ---- */
    .page-header {
      background: #185FA5;
      color: #FFFFFF;
      padding: 1.5rem 2rem;
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

<script>
(function () {
  function initPanel(panel) {
    if (!panel || panel.dataset.initialized === "true") return;
    var slug = panel.dataset.slug;
    var initName = "initBloque_" + slug;

    function runInit() {
      if (typeof window[initName] === "function") {
        window[initName]();
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
    raw = response.content[0].text.strip()
    visualizacion = _parse_visualizacion(raw, elemento)

    if verbose and visualizacion.get("VISUALIZABLE") != "NO":
        print(f"\n[{nombre}]")
        print(f"  Patrón: {visualizacion['PATRON']}")
        print(f"  Eje X: {visualizacion['EJE_X']}")
        print(f"  Eje Y: {visualizacion['EJE_Y']}")
        print(f"  Justificación: {visualizacion['JUSTIFICACION']}")
        if visualizacion.get("RANGO_VARIABLES"):
            print(f"  Rangos: {visualizacion['RANGO_VARIABLES']}")
        if visualizacion.get("ZONA_VALIDEZ"):
            print(f"  Zona validez: {visualizacion['ZONA_VALIDEZ']}")

    return visualizacion


def evaluar_advertencia(elemento: dict) -> str | None:
    """Evalúa valor pedagógico en detección; retorna RAZON o None.

    Usado por detector.py para rellenar el campo ``advertencia`` del
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
                print(
                    f'[RANGOS] Variable "{nombre_orig}" no encontrada en el HTML '
                    f"— slider no corregido"
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
                print(
                    f'[RANGOS] Variable "{nombre_orig}" no encontrada en el HTML '
                    f"— slider no corregido"
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
            print(
                f"{prefijo}Rango incorrecto para {variable}: "
                f"esperado default={default_str}"
            )


def validar_bloque_html(bloque: str, slug: str) -> bool:
    """Comprueba que el bloque incluye initBloque completo y no está truncado."""
    nombre_funcion = "initBloque_" + slug
    tiene_funcion = nombre_funcion in bloque
    stripped = bloque.rstrip()
    tiene_cierre = stripped.endswith("</script>") or stripped.endswith("};")
    return tiene_funcion and tiene_cierre


def _bloque_placeholder(slug: str, nombre: str) -> str:
    """HTML de reserva cuando Sonnet devuelve un bloque truncado o inválido."""
    nombre_esc = nombre.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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
        f"<script>window['initBloque_{slug}'] = function() {{}};</script>"
        "</div>"
    )


def _generar_bloque(
    elemento: dict,
    idx: int,
    verbose: bool = False,
    texto_original: str | None = None,
) -> tuple[int, str]:
    """Call Sonnet to generate the interactive HTML panel for one element.

    Paso 1: razonador de visualización (patrón adaptativo).
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

    Returns:
        (idx, html_block) where html_block is the Sonnet-generated HTML
        fragment or an error panel div.
    """
    nombre = elemento.get("nombre", f"Elemento {idx + 1}")
    slug = _slug(nombre)
    advertencia = elemento.get("advertencia")

    if verbose and advertencia:
        print(
            f'[GENERADOR] Elemento "{nombre}" generado con advertencia: '
            f"{advertencia}"
        )

    last_exc: Exception | None = None
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=float(REQUEST_TIMEOUT_SECONDS),
    )

    try:
        visualizacion = _razonar_visualizacion(
            elemento, client, verbose=verbose, texto_original=texto_original
        )
    except Exception as exc:  # noqa: BLE001
        if verbose:
            print(f"\n[{nombre}] Razonador falló: {exc} — usando CURVA_SIMPLE")
        visualizacion = _fallback_visualizacion(elemento)

    if visualizacion.get("VISUALIZABLE") == "NO":
        visualizacion = _fallback_visualizacion(elemento)

    rangos_raw = visualizacion.get("RANGO_VARIABLES", "")
    if verbose:
        print(
            f"[GENERADOR] Rangos para {nombre}: "
            f"{rangos_raw or 'NO ENCONTRADO'}"
        )

    user_msg = build_generador_message(elemento, visualizacion, slug)
    rangos_esperados = _parse_rango_variables(rangos_raw)
    parametros_slider = visualizacion.get("PARAMETROS_SLIDER", "")

    bloque_incompleto = False
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL_SMART,
                max_tokens=_MAX_TOKENS_HTML,
                system=PROMPT_GENERADOR_HTML,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text.strip()

            # Strip accidental backtick code fences despite prompt instructions
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw).strip()

            if getattr(response, "stop_reason", None) == "max_tokens":
                bloque_incompleto = True
                print(
                    f"[GENERADOR] Respuesta truncada (max_tokens) "
                    f"para slug={slug!r} — intento {attempt + 1}"
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
                if validar_bloque_html(raw, slug):
                    if rangos_esperados:
                        validar_rangos(
                            raw,
                            rangos_esperados,
                            nombre,
                            parametros_slider=parametros_slider,
                        )
                    return idx, raw

            if _is_valid_html(raw):
                bloque_incompleto = True
                print(
                    f"[GENERADOR] Bloque incompleto para slug={slug!r} "
                    f"(falta initBloque_{slug} o cierre de script) "
                    f"— intento {attempt + 1}"
                )
                last_exc = ValueError(
                    f"Bloque HTML incompleto para initBloque_{slug}"
                )
                continue

            last_exc = ValueError(
                f"Intento {attempt + 1}: respuesta sin HTML valido "
                f"(primeros 120 chars: {raw[:120]!r})"
            )

        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    if bloque_incompleto:
        return idx, _bloque_placeholder(slug, nombre)

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
