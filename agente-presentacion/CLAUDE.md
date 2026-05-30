# Agente Presentación — Estado del proyecto

**Repositorio:** `berns-dev/agente-presentacion-tfg`
**Última actualización:** 2026-05-30

---

## Propósito

Genera material de presentación a partir del Markdown estructurado producido por el Agente
Contenido. Dos formatos de salida: PDF académico (ReportLab, puro Python) y página HTML
interactiva con controles paramétricos y gráficas Chart.js generados por Sonnet.

**Principio rector:** Extrae y reformatea. No inventa. El texto que aparece en el output
proviene exclusivamente del Markdown de entrada.

---

## Estado

| Módulo | Estado |
|---|---|
| `config.py` | ✅ Completo |
| `prompts.py` | ✅ Completo (sistema + constructores) |
| `detector.py` | ✅ Completo — detección 100% regex, agrupación por sección |
| `generador_pdf.py` | ✅ Completo — pipeline ReportLab con LaTeX como monospace |
| `generador_html.py` | ✅ Completo — Sonnet + ThreadPoolExecutor + sistema de pestañas CSS |
| `app.py` | ✅ Completo — PDF y HTML interactivo ambos habilitados |

**Validado con `Tema 1_curado.md`: PDF correcto (30 KB, header `%PDF-`).**

---

## Stack técnico

- **UI:** Streamlit (`layout="wide"`, sidebar para upload y acciones)
- **API:** Anthropic directo
  - `claude-sonnet-4-5` — generación de bloques HTML interactivos en `generador_html.py`
  - `claude-haiku-4-5-20251001` — definido en `prompts.py` para desambiguación futura (no cableado aún; ver sección detector)
- **PDF:** `reportlab` + `markdown` (puro Python, sin GTK, funciona en Windows)
- **HTML interactivo:** Chart.js (CDN) + MathJax (CDN) + JS/sliders generados por Sonnet
- **Credenciales:** `.env` + `python-dotenv`

---

## Arquitectura de archivos

```
app.py              — UI Streamlit + detección + selección + generación
detector.py         — detección 100% regex, agrupación por sección
generador_pdf.py    — pipeline Markdown → PDF académico (ReportLab)
generador_html.py   — pipeline elementos → HTML interactivo (Sonnet + ThreadPoolExecutor)
prompts.py          — system prompts y constructores de mensajes
config.py           — constantes y carga de .env
```

---

## Flujo principal

1. **Upload** — usuario sube un `.md` generado por el Agente Contenido
2. **Detección** — `detectar_elementos(markdown_text)` extrae secciones con contenido matemático
3. **Selección** — checkboxes por sección; "Seleccionar todo" / "Ninguno"
4. **Generación** — usuario elige formato:
   - "Generar PDF completo" (sidebar) → `generar_pdf(markdown_text)` → bytes → descarga
   - "Generar HTML interactivo" (área principal) → `generar_html(elementos_sel, md, titulo)` → `.html` → descarga

---

## Decisiones de implementación clave

### Detección de secciones (`detector.py: detectar_elementos()`)

La detección es **100% determinista mediante regex**. No hay llamada a Haiku.

Pipeline de 4 fases:
1. **Regex determinista:** detecta `$$...$$`, `$...$` y tablas Markdown (≥40% celdas numéricas). Registra posición y sección más cercana.
2. **Extracción de secciones:** `_extraer_textos_secciones()` devuelve el cuerpo completo de cada sección para usarlo como contexto rico.
3. **Agrupación por sección:** todos los items de la misma sección (encabezado `##`/`###`) se agrupan en un único elemento. El nombre del elemento es el título del encabezado.
4. **Un elemento por sección:** tipo dominante (`relacion` > `ecuacion` > `tabla`), expresión concatenada, contexto completo (máx. 3000 chars).

Esto produce ~5-8 checkboxes (uno por sección con contenido matemático) en lugar de ~20-30 (uno por ecuación individual).

**`PROMPT_DETECTOR_INTERACTIVIDAD` y `build_detector_message()` en `prompts.py`** están definidos pero no cableados. La detección actual no los necesita porque los nombres vienen de los encabezados Markdown. Hay un `TODO` en `detector.py` para integrar la llamada a Haiku en casos de secciones sin encabezado o con nombre demasiado genérico.

### Estructura del elemento detectado
```python
{
    "id":        int,   # índice 0-based en orden de aparición
    "tipo":      str,   # "ecuacion" | "relacion" | "tabla"
    "nombre":    str,   # título del encabezado de sección
    "expresion": str,   # todas las expresiones de la sección ($$...$$ o $...$)
    "contexto":  str,   # texto completo de la sección, máx. 3000 chars
    "seccion":   str,   # mismo que nombre
    "es_bloque": True,  # siempre True (nivel de sección)
}
```

### Pipeline PDF (`generador_pdf.py`)

Usa **ReportLab** (puro Python, sin GTK, funciona en Windows sin dependencias del sistema).

Pipeline en `generar_pdf()`:
1. Strip frontmatter YAML
2. `_protect_latex()` — reemplaza `$$...$$` e `$...$` con tokens seguros antes de que el parser markdown los rompa
3. Sustituye `[FIGURA: ...]` por texto italizado; `[TEXTO_ILEGIBLE]` por un blockquote italic visible (`> *[Contenido no legible en el material original]*`) para que el profesor sepa que hay una laguna
4. `markdown()` → HTML
5. `_MarkdownFlowableParser` — HTMLParser custom que convierte H1/H2/H3/H4, párrafos, listas, bloques de código y ecuaciones a Flowables de ReportLab
6. Las ecuaciones LaTeX aparecen como texto monoespaciado en `_LeftBorderBox` (fondo `#F7F5F0`, borde izquierdo `#185FA5`)
7. `BaseDocTemplate` + pie de página con título y número de página → bytes

Función auxiliar `generar_html_academico()` disponible como fallback ligero (no llamada desde `app.py` en condiciones normales).

### Pipeline HTML interactivo (`generador_html.py`)

Genera una página HTML autocontenida con sistema de pestañas CSS puro:
1. Por cada elemento seleccionado: llamada paralela a Sonnet (`MODEL_SMART`) con `build_generador_message()` — hasta `_MAX_RETRIES=2` reintentos si la respuesta no es HTML válido.
2. `ThreadPoolExecutor(max_workers=4)` — llamadas paralelas; orden restaurado por índice original (no por orden de finalización).
3. Si falla un elemento: panel de error visible sin interrumpir el resto.
4. `_construir_pagina()` ensambla los bloques en `_HTML_TEMPLATE` usando `<!--MARKER-->` (evita conflictos con `{}` de CSS en `str.format()`).

Sistema de pestañas: radio inputs ocultos antes del `.tabs-wrapper` en el DOM; selector CSS `#input-id:checked ~ .tabs-wrapper #panel-id { display: block; }`. MathJax y Chart.js cargados una sola vez en `<head>`.

### Compatibilidad dark/light mode
- **`st.markdown` CSS:** `var(--background-color)`, `var(--secondary-background-color)`, `var(--text-color)` de Streamlit
- **Iframes:** JS `sync()` lee luminancia del fondo del padre cada 800ms; aplica `.dark`/`.light` en `:root`; `@media(prefers-color-scheme:dark)` como fallback offline

---

## Identidad visual (compartida con la suite)

- **Tipografía:** Playfair Display (títulos) + DM Sans (cuerpo), vía Google Fonts CDN
- **Acento:** `#185FA5` — fijo, identidad de marca
- **Hero:** workflow de 4 pasos (Markdown → Detectar → Seleccionar → Generar)
- **Layout:** `layout="wide"`, sidebar para upload + botón PDF; área principal para detección, selección y botón HTML

---

## Prompts (`prompts.py`)

### `PROMPT_GENERADOR_HTML`
Para Sonnet. Genera bloques HTML con cabecera MathJax, explicación contextual, sliders,
resultado en tiempo real, gráfica Chart.js v4 e interpretación dinámica por rangos.
Restricciones: IDs con prefijo `bloque_<slug>`, Chart.js destruido antes de recrear,
CSS/JS inline, paleta `#F7F5F0` / `#185FA5`. HTML directo sin backticks ni texto adicional.
Constructor: `build_generador_message(nombre, latex, variables_entrada, variable_salida, contexto)`.

### `PROMPT_DETECTOR_INTERACTIVIDAD`
Para Haiku. Definido pero no cableado. Formato de salida: `<INTERACTIVO>`, `<TIPO>`, `<NOMBRE>`, `<VARIABLES>`.
Constructor: `build_detector_message(fragmento)`.
Ver TODO en `detector.py`.

---

## Configuración (`config.py` / `.env`)

```
ANTHROPIC_API_KEY=           — obligatorio
MODEL_FAST=claude-haiku-4-5-20251001
MODEL_SMART=claude-sonnet-4-5
REQUEST_TIMEOUT_SECONDS=120
MIN_LATEX_CHARS=3
MIN_VARIABLES_FOR_RELACION=2
CONTEXTO_CHARS=350
```

---

## Limitaciones documentadas

1. **LaTeX no renderizado en PDF:** las ecuaciones aparecen en monospace con borde azul, no como símbolos matemáticos. ReportLab no tiene renderizador LaTeX nativo; la alternativa (matplotlib mathtext) añadiría dependencias externas.
2. **Detección de tablas:** umbral del 40% de celdas numéricas puede excluir tablas mixtas.
3. **Haiku no integrado en detector:** `PROMPT_DETECTOR_INTERACTIVIDAD` definido pero no cableado. Secciones sin encabezado usan los primeros 6 tokens del contexto como nombre.
4. **Rate limit en HTML:** con muchos elementos seleccionados, `ThreadPoolExecutor(4)` puede agotar el rate limit de Sonnet. El panel de error por elemento hace el fallo visible sin abortar el resto.

---

## Changelog

| Fecha | Cambio |
|---|---|
| 2026-05-30 | Scaffold inicial. Todos los módulos creados. |
| 2026-05-30 | `generador_html.py` implementado completamente (Sonnet + ThreadPoolExecutor + pestañas CSS). |
| 2026-05-30 | `generador_pdf.py` reescrito con ReportLab (elimina WeasyPrint y matplotlib). Validado con Tema 1_curado.md. |
| 2026-05-30 | `detector.py` reescrito con agrupación por sección (un elemento por `##`/`###`, no por ecuación). |
| 2026-05-30 | CLAUDE.md actualizado para reflejar el estado real del código. |
