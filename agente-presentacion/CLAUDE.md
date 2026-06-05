# Agente Presentación — Estado del proyecto

**Última actualización:** 2026-06-05

---

## 1. PROPÓSITO

Genera dos salidas desde el Markdown producido por el Agente Contenido: un PDF académico con ecuaciones renderizadas y una página HTML autocontenida con visualizaciones interactivas.

**Inputs:**
- `[obligatorio]` Archivo `.md` del Agente Contenido.
- `[opcional]` PDF o PPTX del material original del profesor. Si se sube, el razonador lo usa para determinar rangos físicos realistas de las variables y ajustar el patrón de visualización. Sin este archivo el agente funciona igual, pero los rangos de los sliders se infieren solo del contexto del Markdown.

**Outputs:**
- PDF con ReportLab: ecuaciones como imágenes PNG (matplotlib mathtext), tablas, headings, pie de página.
- HTML autocontenido: una pestaña por sección seleccionada, con Chart.js o canvas nativo según el patrón elegido dinámicamente por el razonador.

El patrón de visualización no está fijado de antemano. Para cada sección, Sonnet primero decide si la relación merece representación interactiva y qué patrón aplicar; luego un segundo Sonnet genera el HTML para ese patrón.

---

## 2. ARQUITECTURA DE ARCHIVOS

```
app.py              — UI Streamlit; extracción de texto del PDF/PPTX opcional;
                      priorización de páginas por densidad numérica; triggers
                      de detección, PDF y HTML; checkboxes de selección
detector.py         — Detección 100% regex de ecuaciones y tablas; agrupa
                      por sección (un elemento por ##/###, no por ecuación)
generador_pdf.py    — Markdown → PDF: protege LaTeX, convierte a HTML,
                      parsea HTML a Flowables ReportLab; renderiza ecuaciones
                      con matplotlib mathtext
generador_html.py   — Pipeline por elemento: razonador Sonnet → generador Sonnet;
                      post-procesado Python de rangos (aplicar_rangos);
                      ThreadPoolExecutor; plantilla HTML con pestañas CSS
prompts.py          — PROMPT_RAZONADOR_VISUALIZACION, PROMPT_GENERADOR_HTML,
                      PROMPT_DETECTOR_INTERACTIVIDAD (sin cablear);
                      build_razonador_message, build_generador_message
config.py           — Carga centralizada de .env; MODEL_FAST/MODEL_SMART;
                      MIN_LATEX_CHARS, MIN_VARIABLES_FOR_RELACION, CONTEXTO_CHARS
requirements.txt    — anthropic, streamlit, reportlab, markdown,
                      matplotlib, python-dotenv, pdfplumber, python-pptx
```

---

## 3. FLUJO DE EJECUCIÓN COMPLETO

**Carga de archivos (sidebar):**
1. El profesor sube el `.md` del Agente Contenido. El MD se guarda en `session_state["md_content"]`; el hash MD5 detecta cambios y resetea el estado.
2. Opcionalmente sube un PDF o PPTX. `_extraer_texto_original()` extrae el texto y lo guarda en `session_state["texto_original"]`. Para PDF, `_extraer_texto_pdf_inteligente()` selecciona hasta 5 páginas: las 2 primeras siempre, más las de mayor densidad numérica (conteo de patrones `\d+\.?\d*\s*(?:MPa|GPa|mm|...)` por página). El texto queda truncado a 8.000 caracteres.

**Detección:**
3. El profesor pulsa "Detectar elementos" → `detectar_elementos(md_content)` en `detector.py`.
4. La función aplica regex para encontrar bloques `$$...$$`, expresiones `$...$` y tablas Markdown con al menos 40% de celdas numéricas. Agrupa todos los elementos de la misma sección en uno, con tipo dominante (relación > ecuación > tabla) y nombre igual al título del encabezado. Devuelve un elemento por sección.
5. La UI muestra los elementos como checkboxes agrupados por tipo (ecuación, relación paramétrica, tabla numérica).

**Generación de PDF** (independiente de la selección):
6. El botón "Generar PDF completo" en la barra lateral llama a `generar_pdf(md, titulo)`. El PDF se almacena en `session_state["pdf_bytes"]` y queda disponible para descarga inmediata.

**Generación de HTML interactivo:**
7. El profesor selecciona las secciones y pulsa "Generar HTML (N elementos)".
8. `generar_html(elementos_sel, md, titulo, verbose, texto_original)` abre un `ThreadPoolExecutor` (máx. 4 workers) y llama a `_generar_bloque()` por elemento en paralelo.
9. Por cada elemento, en `_generar_bloque()`:
   - **Paso 1 — Razonador (Sonnet):** `_razonar_visualizacion()` llama a Sonnet con `PROMPT_RAZONADOR_VISUALIZACION` y `build_razonador_message()`. El mensaje incluye el texto del material original si está disponible. Sonnet devuelve XML con `VISUALIZABLE`, `PATRON`, ejes, sliders, `RANGO_VARIABLES` y `ZONA_VALIDEZ`.
   - Si el razonador devuelve `VISUALIZABLE=NO`, se aplica igualmente el fallback CURVA_SIMPLE. El elemento no se descarta porque el profesor lo seleccionó explícitamente.
   - **Paso 2 — Generador (Sonnet):** `build_generador_message()` pasa el elemento, la decisión del razonador y el `slug` exacto. Sonnet genera el bloque HTML (máx. 8.192 tokens).
   - **Post-procesado — `aplicar_rangos()`:** antes de validar, Python sobreescribe los atributos `min`, `max` y `value` de cada `input[type=range]` con los valores de `RANGO_VARIABLES`. Esto corrige los casos donde Sonnet recibe los rangos correctos del razonador pero los ignora en la generación (ver sección 7).
   - **Validación — `validar_bloque_html()`:** comprueba que el bloque contiene `initBloque_{slug}` y no está truncado. Si falla tras `_MAX_RETRIES=2` intentos, inserta un panel de error o un placeholder visible.
10. Los resultados se ordenan por índice original (no por orden de finalización).
11. `_construir_pagina()` envuelve los bloques en `_HTML_TEMPLATE` inyectando el sistema de pestañas CSS e inicialización lazy.

---

## 4. MODELOS Y CUÁNDO SE USAN

| Tarea | Modelo | Justificación |
|---|---|---|
| Detección de secciones | ninguno (regex) | El contenido matemático en Markdown con formato correcto es identificable sin ambigüedad |
| Evaluación de valor pedagógico (`evaluar_advertencia`) | Sonnet (`MODEL_SMART`) | Llamada previa a la detección para rellenar el campo `advertencia`; reutiliza `_razonar_visualizacion` |
| Razonador de visualización por elemento | Sonnet (`MODEL_SMART`) | Requiere razonar sobre contexto físico y elegir entre 6 patrones |
| Generador de bloque HTML | Sonnet (`MODEL_SMART`) | Genera lógica JS compleja adaptada al patrón; 8.192 tokens de salida |
| Desambiguación tipo/nombre (`PROMPT_DETECTOR_INTERACTIVIDAD`) | Haiku (`MODEL_FAST`) | Definido en `prompts.py`; **no está cableado en el flujo actual** |

---

## 5. SISTEMA DE RAZONAMIENTO DE VISUALIZACIÓN

El razonador evalúa primero el valor pedagógico del elemento antes de elegir patrón.

**Criterio VISUALIZABLE SI/NO:** Sonnet lee el texto completo del fragmento y responde internamente: "¿Qué comprensión nueva obtiene el alumno al mover un slider que no pueda obtener leyendo el texto?" Si la respuesta es "ninguna", devuelve `<VISUALIZABLE>NO</VISUALIZABLE>` con una razón. Casos típicos de NO: observaciones empíricas con factor fijo (E/10), definiciones con una variable sin rango útil, descripciones cualitativas con algún símbolo pero sin relación funcional explorable.

**Qué pasa cuando el razonador devuelve NO:** `_parse_visualizacion()` detecta el NO y devuelve un dict con `VISUALIZABLE=NO`. `_generar_bloque()` lo sustituye por el fallback CURVA_SIMPLE y genera el HTML igualmente, porque el profesor decidió seleccionar ese elemento. No hay bloqueo ni omisión.

**Los 6 patrones:**

| Patrón | Criterio de selección | Tecnología |
|---|---|---|
| `CURVA_SIMPLE` | Una dependiente, una independiente, sin parámetros secundarios relevantes. Fallback por defecto. | Chart.js línea; escala log si el razonador lo indica |
| `FAMILIA_CURVAS` | Una dependiente, una independiente, más uno o dos parámetros que modulan la respuesta. | Chart.js multilínea: 4 curvas para mín/33%/66%/máx del parámetro; activa en #185FA5, resto en #CCCCCC |
| `REGION_CRITERIO` | La expresión define una frontera entre dos estados (seguro/falla, válido/inválido). | Chart.js scatter: zonas verde/rojo con fill, punto móvil controlado por sliders |
| `MAPA_2D` | Tres o más variables con peso comparable. | Canvas HTML5 nativo, grid 80×80, escala #185FA5 → blanco → #C0392B; sin Chart.js |
| `TRAYECTORIA` | La expresión describe un proceso en un espacio de estados (P-V, T-S, tensión-deformación). | Chart.js scatter+línea; slider de progreso 0-100% |
| `RESPUESTA_FRECUENCIAL` | Variable independiente es frecuencia o tiempo, respuesta dinámica. | Dos Chart.js apilados (magnitud y fase); eje X logarítmico |

---

## 6. DETECTOR — FILTRADO DE FALSOS POSITIVOS

El detector aplica tres capas de filtrado en orden antes de mostrar un elemento al profesor.

**Capa 1 — `es_constante_pura()` (Python, sin API):** descarta expresiones LaTeX que son valores numéricos fijos sin variables simbólicas explorables. Cubre constantes empíricas (`10^8`, `10^{11}`) y ratios fijos (`E/1000`, `E/10`). Las tablas Markdown no pasan por este filtro.

**Capa 2 — Criterio pedagógico en Haiku:** el prompt exige que el elemento cumpla dos condiciones: (1) relación matemática entre variables, no una constante ni una definición; (2) al menos una variable con rango de exploración con significado pedagógico. Haiku devuelve también `<CONFIANZA>` ALTA/MEDIA/BAJA.

**Capa 3 — Filtro `<CONFIANZA>`:** solo pasan al profesor los elementos con confianza ALTA o MEDIA. Los de confianza BAJA se descartan antes de llegar a la UI y al razonador.

El campo `advertencia` del razonador es complementario. Cubre los elementos que superan las tres capas del detector pero que Sonnet considera de baja interactividad pedagógica después de leer el contexto físico completo. Los dos sistemas no se solapan: el detector filtra lo obvio con Python y con Haiku barato; el razonador filtra los casos ambiguos con comprensión física real.

---

## 7. PIPELINE PDF

Función pública: `generar_pdf(markdown_text, titulo)` en `generador_pdf.py`.

1. **Strip frontmatter YAML** (`---...---`).
2. **`_protect_latex()`:** reemplaza `$$...$$` e `$...$` con tokens placeholder para que el parser de Markdown no los altere.
3. **Marcadores del Agente Contenido:** `[FIGURA: ...]` → caption en cursiva; `[TEXTO_ILEGIBLE]` → blockquote italic que indica la laguna al profesor.
4. **Markdown → HTML** con la biblioteca `markdown` (extensiones `tables`, `fenced_code`).
5. **`_MarkdownFlowableParser`** (HTMLParser custom): H1-H4 → estilos jerárquicos en azul/negro/gris; párrafos justificados; listas `ul`/`ol` con contador; `blockquote` en cursiva; `pre` en Courier monoespaciado; celdas `td`/`th` como párrafos indentados (sin layout de tabla real).
6. **Ecuaciones en bloque** (`$$...$$`): `render_latex_to_image()` renderiza la expresión con `matplotlib.mathtext` (`usetex=False`, sin LaTeX del sistema) como PNG en memoria. La imagen se escala para no superar el 80% del ancho de página. Si el renderizado falla, fallback a texto Courier en `_LeftBorderBox`.
7. **Ecuaciones inline** (`$...$`): renderizadas como `<img>` inline escaladas a 12pt de altura; fallback a `<font name="Courier">`.
8. **`_LeftBorderBox`:** Flowable custom con fondo `#F7F5F0` y borde izquierdo `#185FA5` (3pt). Envuelve código y ecuaciones en fallback.
9. **`BaseDocTemplate`** con pie de página: título + número de página, fuente Helvetica 8pt, línea separadora `#D3D1C7`.
10. Las imágenes PNG temporales se escriben a disco y se eliminan en el bloque `finally`.

---

## 8. POST-PROCESADO DE RANGOS (`aplicar_rangos`)

**Por qué existe (Caso C):** Sonnet recibe los rangos correctos del razonador (`RANGO_VARIABLES`) en el mensaje de usuario, pero los ignora durante la generación y produce sliders con valores por defecto arbitrarios (min=0, max=100, value=50). Esto ocurre de forma inconsistente, no en todos los elementos ni en todos los intentos.

**Qué hace `aplicar_rangos(html_bloque, rangos, verbose)`:**
- Parsea el campo `RANGO_VARIABLES` del razonador a un dict `{variable: {min, max, default}}` mediante `_parse_rango_variables()`.
- Itera todos los `input[type=range]` del HTML generado con regex.
- Para cada input, extrae el atributo `id` y lo compara contra los nombres de variable normalizados con `normalizar_nombre()`.
- Si encuentra coincidencia, sobreescribe los atributos `min`, `max` y `value` con los valores del razonador.
- Si `verbose=True`, imprime qué variables no encontraron slider en el HTML.

**`normalizar_nombre(nombre)`:** convierte símbolos especiales y letras griegas a ASCII para que el matching de IDs funcione aunque Sonnet use nombres distintos en el HTML que en el XML del razonador. Ejemplos: `σ₀` → `sigma0`, `ρ` → `rho`, `θ` → `theta`.

**Cuándo se llama:** en `_generar_bloque()`, después de que el HTML supera `_is_valid_html()` y antes de `validar_bloque_html()`. Si no hay rangos en la respuesta del razonador, `aplicar_rangos()` retorna el HTML sin modificar.

---

## 9. CONVENCIONES CRÍTICAS

**IDs en HTML generado por Sonnet:**
Todos los IDs deben tener el prefijo `bloque_{slug}_`. El slug se construye en Python con `_slug(nombre)` y se pasa explícitamente a Sonnet como `SLUG_EXACTO` en el mensaje de usuario. Sonnet no debe derivarlo por su cuenta: el prompt indica que el nombre de la función de inicialización debe ser `window['initBloque_{SLUG_EXACTO}']` con el valor exacto recibido.

**Inicialización lazy (obligatorio):**
Todo el código de inicialización de Chart.js debe estar dentro de `window['initBloque_{slug}'] = function() { ... }`. Esta función se llama desde el JS del contenedor cuando la pestaña se activa, después de que MathJax termine. No usar `DOMContentLoaded` ni ejecución inmediata para crear charts.

**Destrucción previa de Chart.js:**
Dentro de `initBloque_{slug}()`, antes de `new Chart(...)`:
```js
if (window[chartId]) window[chartId].destroy();
```
Omitir esto provoca errores de canvas duplicado al cambiar de pestaña.

**CDNs solo en el contenedor:**
MathJax y Chart.js se cargan en el `<head>` de `_HTML_TEMPLATE`. Los bloques generados por Sonnet no deben incluirlos. El prompt lo indica en la sección IMPORTANTE.

**`.env` centralizado:**
`config.py` hace `load_dotenv(ENV_PATH)` con ruta absoluta. No llamar a `load_dotenv()` en otros módulos.

**Orden en el pipeline por elemento:**
`aplicar_rangos()` debe ejecutarse siempre antes de `validar_bloque_html()`. Cambiar ese orden hace que la validación compruebe atributos que aún no han sido corregidos.

**Paleta fija:**
- Acento: `#185FA5` / hover: `#0C447C`
- Fondo de página: `#F7F5F0`
- Superficie de card: `#FFFFFF`
- Superficie de control (sliders): `#F0EEE9`
- Borde sutil: `rgba(0,0,0,0.08)`

---

## 10. DEPURACIÓN

**Activar verbose:**
```python
html_str = generar_html(elementos_sel, md, titulo, verbose=True, texto_original=texto)
```
`verbose=True` es el valor por defecto en `generar_html()`.

**Qué imprime en cada fase:**

| Fase | Log ejemplo |
|---|---|
| Razonador (patrón) | `[Ley de Hooke] Patrón: CURVA_SIMPLE / Eje X: ε / Eje Y: σ [MPa]` |
| Razonador (rangos) | `[Ley de Hooke] Rangos: E: min=70, max=210, default=200` |
| Razonador (fallo) | `[Nombre] Razonador falló: <excepción> — usando CURVA_SIMPLE` |
| Generador (advertencia) | `[GENERADOR] Elemento "X" generado con advertencia: Sin valor pedagógico` |
| Generador (rangos) | `[GENERADOR] Rangos para X: E: min=70, max=210, default=200` |
| Generador (truncado) | `[GENERADOR] Respuesta truncada (max_tokens) para slug='ley-de-hooke' — intento 1` |
| Generador (incompleto) | `[GENERADOR] Bloque incompleto para slug='ley-de-hooke' (falta initBloque_...)` |
| Rangos (no encontrado) | `[RANGOS] Variable "E" no encontrada en el HTML — slider no corregido` |
| Validación | `[ADVERTENCIA] Ley de Hooke: Rango incorrecto para E: esperado default=200` |

**Qué verificar por patrón:**
- Todos: MathJax renderiza la ecuación en la cabecera del panel (abrir consola del navegador y comprobar que no hay errores de MathJax).
- Chart.js (todos excepto MAPA_2D): sin errores de canvas en consola; sliders actualizan la gráfica.
- MAPA_2D: el canvas dibuja el heatmap al cargar; los sliders disparan `'input'` y recalculan.
- Si un bloque muestra el placeholder ("No se pudo generar la visualización"), el stop_reason fue `max_tokens`. Reducir el número de elementos seleccionados simultáneamente.

---

## 11. PENDIENTE

**`PROMPT_DETECTOR_INTERACTIVIDAD` (Haiku) no está cableado.** El prompt y `build_detector_message()` están definidos en `prompts.py`. La detección actual es 100% regex. Hay un TODO en `detector.py` para integrar la llamada en secciones sin encabezado o con nombre de menos de 3 palabras; mientras tanto, esas secciones usan los primeros 6 tokens del contexto como nombre.

**Tablas en el PDF sin layout de tabla.** Las celdas `td`/`th` se renderizan como párrafos indentados. `_MarkdownFlowableParser` no usa el Flowable `Table` de ReportLab.

**`generar_html_academico()` no expuesta en la UI.** Existe en `generador_pdf.py` como fallback HTML sin ReportLab; `app.py` no la llama.
