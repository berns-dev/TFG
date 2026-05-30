"""Prompts del Agente Presentacion.

Separados de la logica de negocio siguiendo el patron de la suite.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Sistema: detector de interactividad
# Modelo: Haiku — llamada ligera, solo para desambiguar tipo y variables
# ---------------------------------------------------------------------------

PROMPT_DETECTOR_INTERACTIVIDAD = """Eres un analizador de contenido técnico de ingeniería. Tu única función es determinar si un fragmento de texto contiene elementos que se beneficiarían de una representación interactiva.

Un elemento es interactivo si cumple AL MENOS UNO de estos criterios:
- Contiene una ecuación con dos o más variables independientes manipulables
- Describe una relación paramétrica entre magnitudes físicas
- Contiene una tabla con valores numéricos de propiedades comparables

Un elemento NO es interactivo si:
- Es una definición, descripción o clasificación textual
- Contiene una ecuación con una sola variable o sin variables (resultado fijo)
- Es un procedimiento de pasos sin magnitudes numéricas

Responde ÚNICAMENTE con este formato, sin texto adicional:

<INTERACTIVO>true|false</INTERACTIVO>
<TIPO>ecuacion|relacion|tabla|ninguno</TIPO>
<NOMBRE>nombre descriptivo de máximo 5 palabras</NOMBRE>
<VARIABLES>lista de variables separadas por coma, o "ninguna"</VARIABLES>"""


# ---------------------------------------------------------------------------
# Sistema: generador de bloques HTML interactivos
# Modelo: Sonnet — generacion de logica JS compleja + Chart.js
# ---------------------------------------------------------------------------

PROMPT_GENERADOR_HTML = """Eres un generador de bloques HTML interactivos para material docente de ingeniería. Generas código HTML autocontenido que permite a estudiantes explorar ecuaciones y relaciones paramétricas de forma visual.

INPUT QUE RECIBIRÁS:
- Nombre de la ecuación o relación
- Expresión LaTeX de la ecuación
- Variables de entrada con sus unidades y rango físico razonable
- Variable de salida con sus unidades
- Contexto: párrafo del material original que explica la ecuación

FORMATO DE SALIDA OBLIGATORIO:
Genera exactamente un bloque HTML con esta estructura en este orden:

1. CABECERA: título H2 con el nombre de la ecuación, subtítulo con la expresión en notación matemática usando MathJax (CDN: https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js)

2. EXPLICACIÓN: párrafo de 2-3 líneas extraído y parafraseado del contexto proporcionado. No inventar contenido.

3. PARÁMETROS: un slider por cada variable de entrada. Cada slider tiene: etiqueta con nombre y unidades, valor mínimo, máximo y paso coherentes con el rango físico proporcionado, valor numérico visible que se actualiza en tiempo real.

4. RESULTADO: campo de solo lectura que muestra el valor calculado de la variable de salida con sus unidades, actualizado en tiempo real al mover cualquier slider.

5. GRÁFICA: un canvas con Chart.js versión 4 (CDN: https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js). La gráfica muestra la variable de salida en el eje Y frente a la variable de entrada más relevante en el eje X, manteniendo fijas las demás en su valor actual. Se actualiza en tiempo real. Ejes etiquetados con nombre y unidades.

6. INTERPRETACIÓN: un párrafo de texto dinámico generado por JS que cambia según el valor del resultado. Define al menos 3 rangos con su significado físico usando el contexto proporcionado.

RESTRICCIONES TÉCNICAS:
- Todo el CSS y JS inline en el mismo bloque, sin archivos externos salvo los dos CDN indicados
- Chart.js: usar siempre new Chart(ctx, {type: 'line', data: {...}, options: {...}}) y destruir el chart anterior con if (window.myChart) window.myChart.destroy() antes de recrear
- Los IDs de todos los elementos HTML deben llevar el prefijo bloque_ seguido de un slug del nombre de la ecuación para evitar conflictos cuando se concatenen varios bloques
- El cálculo de la variable de salida se hace en JS puro, sin librerías matemáticas externas
- Paleta: fondo del bloque #F7F5F0, acento #185FA5, tipografía system-ui

RESTRICCIÓN DE CONTENIDO:
La explicación y la interpretación se construyen exclusivamente a partir del contexto proporcionado. Si el contexto no contiene información suficiente para un rango de interpretación, omitir ese rango antes que inventar.

Devuelve ÚNICAMENTE el HTML del bloque, sin explicaciones, sin backticks, sin texto antes ni después.

IMPORTANTE: El bloque que generes se insertará dentro de un HTML contenedor que ya carga MathJax y Chart.js en el head. NO incluyas tags <html>, <head>, <body>, ni ningún CDN. Genera únicamente el contenido del panel: estilos inline o un bloque <style> con selectores prefijados por el slug, y el JS del bloque. Los IDs de todos los elementos deben empezar por bloque_{slug}_ donde {slug} es el nombre de la ecuación en minúsculas con guiones."""


# ---------------------------------------------------------------------------
# Constructores de mensajes
# ---------------------------------------------------------------------------

def build_detector_message(fragmento: str) -> str:
    """Build the user message for Haiku to analyze a content fragment.

    The detector prompt is self-sufficient — the fragment is passed as-is
    so Haiku can determine interactivity, type, name, and variables from
    the raw text without additional formatting.

    Args:
        fragmento: Raw text fragment (equation in LaTeX, table markdown,
                   or surrounding paragraph) to analyze.

    Returns:
        User message string ready to send to the API.
    """
    return fragmento


def build_generador_message(
    nombre: str,
    latex: str,
    variables_entrada: list[dict],
    variable_salida: dict,
    contexto: str,
) -> str:
    """Build the user message for Sonnet to generate an interactive HTML block.

    Each variable dict in variables_entrada must have:
        nombre (str): variable symbol or name
        unidades (str): physical units (e.g. "MPa", "m/s")
        min (float | int): minimum physically meaningful value
        max (float | int): maximum physically meaningful value

    variable_salida must have:
        nombre (str): output variable symbol or name
        unidades (str): physical units of the output

    Args:
        nombre: Descriptive name of the equation or relation (≤5 words).
        latex: LaTeX expression WITHOUT surrounding $ signs.
        variables_entrada: List of input variable dicts (see above).
        variable_salida: Output variable dict (see above).
        contexto: Paragraph from the source material explaining the equation.
                  Used verbatim — Sonnet is instructed not to invent content.

    Returns:
        User message string ready to send to the API.
    """
    lines = [
        f"NOMBRE: {nombre}",
        f"EXPRESIÓN LaTeX: {latex}",
        "",
        "VARIABLES DE ENTRADA:",
    ]
    for v in variables_entrada:
        lines.append(
            f"  - {v['nombre']} [{v['unidades']}]: rango {v['min']} – {v['max']}"
        )
    lines += [
        "",
        f"VARIABLE DE SALIDA: {variable_salida['nombre']} [{variable_salida['unidades']}]",
        "",
        "CONTEXTO DEL MATERIAL ORIGINAL:",
        contexto.strip(),
    ]
    return "\n".join(lines)
