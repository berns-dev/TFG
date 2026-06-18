# Agente Presentación — Estado del proyecto

**Última actualización:** 2026-06-18

---

## 0. UI PRINCIPAL — TALLER ITERATIVO (junio 2026)

La vista Presentación en `app-unificada/app.py` usa un **taller por bloque**:

1. El profesor describe la visualización en lenguaje natural (`workshop.generar_desde_instruccion`).
2. Preview embebido en Streamlit; refinamiento con prompts adicionales (`workshop.refinar_html`).
3. Al aprobar: elige **sección ancla** del markdown (`##` / `###`) → guarda en `visualizacion_interactiva`.
4. Puede crear **N visualizaciones** aprobadas por bloque.
5. **Exportar:** PDF del bloque; HTML presentación completa vía `generar_presentacion_con_fragmentos()`.

Módulos legados (`detector.py`, chips de patrón por subbloque) permanecen en el código pero ya no son el flujo principal de la UI.

---

## 1. PROPÓSITO

Genera tres salidas desde el Markdown producido por el Agente Contenido: un PDF académico con plantilla institucional, una página HTML autocontenida con visualizaciones interactivas por pestañas, y un HTML de presentación completa del tema que integra toda la teoría con los bloques interactivos.

**Inputs:**
- `[obligatorio]` Archivo `.md` del Agente Contenido.
- `[opcional]` PDF o PPTX del material original del profesor. Si se sube, el razonador lo usa para determinar rangos físicos realistas y ajustar el patrón. Sin este archivo el agente funciona igual: los rangos se infieren del contexto del Markdown y del conocimiento de ingeniería del modelo (ver sección 5).

**Outputs:**
- PDF con ReportLab: ecuaciones como imágenes PNG (matplotlib mathtext), tablas, headings, pie de página.
- HTML autocontenido: una pestaña por sección seleccionada, con Chart.js o canvas nativo según el patrón elegido dinámicamente por el razonador.
- HTML de presentación completa del tema (`generador_presentacion.py`): documento scrollable que integra toda la teoría del Markdown (secciones H2) con los bloques interactivos de las ecuaciones seleccionadas insertados tras la subsección que las presenta. Sidebar con índice y scroll-spy, navegación anterior/siguiente, botón volver arriba. Inicialización lazy por viewport (IntersectionObserver) — el listener DOMContentLoaded propio de cada bloque se elimina al embeber. SVG esquemáticos opcionales vía Haiku (`PROMPT_GENERADOR_SVG`) solo para marcadores `[FIGURA: ...]` de secciones sin bloque interactivo; si Haiku responde NO_PROCEDE o el SVG no pasa la sanitización (sin script/image/href/url), se mantiene el placeholder gris. Workers limitados a 2 (los documentos completos generan más bloques y agotan el límite de output tokens/min). **Sidebar con desambiguación:** los títulos H2 repetidos (p. ej. "Contenido teórico" varias veces) se numeran solo en el texto visible del índice — "Contenido teórico", "Contenido teórico (2)", … — sin alterar los IDs de sección (`seccion-N`) ni el contenido del documento.

El patrón de visualización no está fijado de antemano. Para cada sección, Sonnet primero decide si la relación merece representación interactiva y qué patrón aplicar; luego un segundo Sonnet genera el HTML para ese patrón.

---

## 2. ARQUITECTURA DE ARCHIVOS

**Punto de entrada UI:** `app-unificada/app.py` — no hay `app.py` standalone en este agente.

```
workshop.py           — taller: generar_desde_instruccion(), refinar_html()
generador_presentacion.py — generar_presentacion_con_fragmentos() + generar_presentacion()
generador_pdf.py    — Markdown → PDF institucional UO
generador_html.py   — razonador + generador (legado / interno)
detector.py         — detección híbrida (legado / interno)
prs_prompts.py      — PROMPT_TALLER_* + prompts del razonador
assets/logo_uniovi.png
tools/razonador_fixture.py — debug CLI del razonador (consume API)
```

Detalle de flujo y prompts en secciones siguientes (la lógica de generación no cambió; la UI pasó a `app-unificada`).

---

## 3. FLUJO DE EJECUCIÓN COMPLETO

**Carga de archivos (sidebar):**
1. El profesor sube el `.md` del Agente Contenido. El MD se guarda en `session_state["md_content"]`; el hash MD5 detecta cambios y resetea el estado.
2. Opcionalmente sube un PDF o PPTX. `_extraer_texto_original()` extrae el texto y lo guarda en `session_state["texto_original"]`. Para PDF, `_extraer_texto_pdf_inteligente()` selecciona hasta 5 páginas: las 2 primeras siempre, más las de mayor densidad numérica (conteo de patrones `\d+\.?\d*\s*(?:MPa|GPa|mm|...)` por página). El texto queda truncado a 8.000 caracteres.

**Detección:**
3. Opcional: checkbox «Analizar advertencias pedagógicas» (Sonnet por elemento; más créditos).
4. El profesor pulsa "Detectar elementos" → `detectar_elementos(md_content, analizar_advertencias=...)`.
5. Regex encuentra bloques `$$...$$`, `$...$` y tablas; agrupa por sección. Fase Haiku filtra candidatos no-tabla (fail-open si la API falla). Fase advertencias solo si opt-in.
6. La UI muestra checkboxes agrupados por tipo.

**Generación de PDF** (independiente de la selección):
6. El botón "Generar PDF completo" en la barra lateral llama a `generar_pdf(md, titulo)`. El PDF se almacena en `session_state["pdf_bytes"]` y queda disponible para descarga inmediata.

**Generación de HTML interactivo:**
7. El profesor selecciona las secciones y pulsa "Generar HTML (N elementos)".
8. `generar_html(elementos_sel, titulo, verbose, texto_original)` abre un `ThreadPoolExecutor` (máx. 4 workers) y llama a `_generar_bloque()` por elemento en paralelo.
9. Por cada elemento, en `_generar_bloque()`:
   - **Paso 1 — Razonador (Sonnet):** `_razonar_visualizacion()` llama a Sonnet con `PROMPT_RAZONADOR_VISUALIZACION` y `build_razonador_message()`. El mensaje incluye el texto del material original si está disponible. Sonnet devuelve XML con `VISUALIZABLE`, `PATRON`, ejes, sliders, `RANGO_VARIABLES` y `ZONA_VALIDEZ`. Los rangos pueden venir del material del profesor, del contexto del Markdown o del conocimiento de ingeniería del modelo — en ese orden de prioridad.
   - Si el razonador devuelve `VISUALIZABLE=NO`, se aplica igualmente el fallback CURVA_SIMPLE. El elemento no se descarta porque el profesor lo seleccionó explícitamente.
   - **Paso 2 — Generador (Sonnet):** `build_generador_message()` pasa el elemento, la decisión del razonador y el `slug` exacto. Sonnet genera el bloque HTML (máx. 8.192 tokens).
   - **Post-procesado — `aplicar_rangos()`:** antes de validar, Python sobreescribe los atributos `min`, `max` y `value` de cada `input[type=range]` con los valores de `RANGO_VARIABLES`. Esto corrige los casos donde Sonnet recibe los rangos correctos del razonador pero los ignora en la generación (ver sección 7).
   - **Validación — `validar_bloque_html()`:** comprueba (1) que existe la definición global `window['initBloque_{slug}'] =`, (2) que existe la llamada de arranque `DOMContentLoaded` → `window['initBloque_{slug}']()`, y (3) que el script no está truncado. Devuelve `(es_valido, motivo)`; si falla tras `_MAX_RETRIES=2` intentos, el placeholder visible indica el motivo exacto.
10. Los resultados se ordenan por índice original (no por orden de finalización).
11. `_construir_pagina()` envuelve los bloques en `_HTML_TEMPLATE` inyectando el sistema de pestañas CSS e inicialización lazy.

---

## 4. MODELOS Y CUÁNDO SE USAN

| Tarea | Modelo | Justificación |
|---|---|---|
| Detección regex (fase 1) | ninguno | Contenido matemático en Markdown con formato correcto |
| Filtro de interactividad (fase Haiku) | Haiku (`MODEL_FAST`) | Descarta constantes empíricas y contexto no manipulable; fail-open si API falla |
| Evaluación de valor pedagógico (`evaluar_advertencia`) | Sonnet (`MODEL_SMART`) | Opt-in en UI; rellena campo `advertencia`; reutiliza `_razonar_visualizacion` |
| Razonador de visualización por elemento | Sonnet (`MODEL_SMART`) | Contexto físico y elección entre 7 patrones |
| Generador de bloque HTML | Sonnet (`MODEL_SMART`) | JS + Chart.js; 8.192 tokens de salida |

---

## 5. SISTEMA DE RAZONAMIENTO DE VISUALIZACIÓN

El razonador evalúa primero el valor pedagógico del elemento antes de elegir patrón.

**Régimen dual de fuentes (decisión de diseño):** el razonador y el generador aplican reglas distintas según el tipo de información. El texto descriptivo y los insights solo pueden venir del contexto del Markdown. La implementación de la ecuación en JS —forma de la curva, rangos de sliders, comportamiento esperado— usa el conocimiento de ingeniería del modelo libremente. Esto es deliberado: la física de una ecuación es objetiva y el modelo no puede "alucinar" que Hall-Petch es hiperbólica, mientras que afirmar algo sobre el material del profesor sí requeriría fuente explícita.

**Criterio VISUALIZABLE SI/NO:** Sonnet lee el texto completo del fragmento y responde internamente: "¿Qué comprensión nueva obtiene el alumno al mover un slider que no pueda obtener leyendo el texto?" Si la respuesta es "ninguna", devuelve `<VISUALIZABLE>NO</VISUALIZABLE>` con una razón. Casos típicos de NO: observaciones empíricas con factor fijo (E/10), definiciones con una variable sin rango útil, descripciones cualitativas con algún símbolo pero sin relación funcional explorable.

**Qué pasa cuando el razonador devuelve NO:** `_parse_visualizacion()` detecta el NO y devuelve un dict con `VISUALIZABLE=NO`. `_generar_bloque()` lo sustituye por el fallback CURVA_SIMPLE y genera el HTML igualmente, porque el profesor decidió seleccionar ese elemento. No hay bloqueo ni omisión.

**Los 7 patrones:**

| Patrón | Criterio de selección | Tecnología |
|---|---|---|
| `CURVA_SIMPLE` | Una dependiente y una independiente, sin parámetro discreto; admite 1-2 sliders solo para parámetros continuos útiles. Fallback por defecto. | Chart.js línea; escala log si el razonador lo indica |
| `FAMILIA_CURVAS` | Una dependiente, una independiente y un parámetro DISCRETO/categórico que define 2-4 curvas (`PARAMETRO_FAMILIA`). | Chart.js multilínea: curvas por los valores de la familia (explícitos si se dan); activa en #185FA5, resto en #CCCCCC |
| `REGION_CRITERIO` | La expresión define una frontera entre dos estados (seguro/falla, válido/inválido). | Chart.js scatter: zonas verde/rojo con fill, punto móvil controlado por sliders |
| `MAPA_2D` | Tres o más variables con peso comparable. | Canvas HTML5 nativo, grid 80×80, escala #185FA5 → blanco → #C0392B; sin Chart.js |
| `TRAYECTORIA` | La expresión describe un proceso en un espacio de estados (P-V, T-S, tensión-deformación). | Chart.js scatter+línea; slider de progreso 0-100% |
| `RESPUESTA_FRECUENCIAL` | Variable independiente es frecuencia o tiempo, respuesta dinámica. | Dos Chart.js apilados (magnitud y fase); eje X logarítmico |
| `ANIMACION_MECANISMO` | El contenido describe un mecanismo cuyo funcionamiento se entiende viendo moverse sus piezas (cilindro de doble efecto, biela-manivela, leva). | SVG en corte animado (sin Chart.js); conjunto móvil en un `<g>` con translate; controles botón toggle + slider de velocidad; animación por `requestAnimationFrame` |

**Clasificación de parámetros (decisión familia vs slider, anti-sliders decorativos):**
Antes de elegir patrón, el razonador clasifica cada parámetro secundario (paso 2 de `PROMPT_RAZONADOR_VISUALIZACION`):
- **(D) discreto/categórico** (material, configuración, n = 2/4/6…) → familia de curvas, no slider.
- **(C) continuo y sensible** (recorrer su rango cambia la curva de forma apreciable, no un mero reescalado) → slider.
- **(F) irrelevante/fijado** (lo fija el ejemplo, solo reescala, o cambio <~15 %) → sin control, queda constante.
Un **test de utilidad del slider** (máx. 2 sliders) impide sliders decorativos: solo es C si variarlo cambia la salida de forma visible y con significado físico. El paso 3 elige la representación por **valor pedagógico** (árbol según nº de D/C), no por encaje técnico.

**Campos XML del razonador** (parseados en ambas copias de `_parse_visualizacion` — `generador_html.py` y `detector.py`):
- `PARAMETRO_FAMILIA`: parámetro discreto y sus 2-4 valores (numéricos o categóricos), o "ninguno".
- `PARAMETROS_SLIDER`: solo símbolos de variables continuas que pasan el test de utilidad.
- `SLIDERS_DESCARTADOS`: variables fijadas/irrelevantes con su motivo.

`build_generador_message()` traslada `PARAMETRO_FAMILIA` al generador y emite la **orden dura "NO CREAR SLIDER"** para las descartadas; la instrucción `FAMILIA_CURVAS` de `PROMPT_GENERADOR_HTML` usa los valores explícitos de la familia. **Retrocompatibilidad:** respuestas sin estos tags → defaults `""` → comportamiento anterior. Validación: `tools/razonador_fixture.py`.

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
El PDF sigue una **plantilla institucional global** (azul UO `#003366`), idéntica para cualquier asignatura — sin excepciones por tema ni materia.

1. **`_extraer_asignatura()`:** nombre de la asignatura para cabecera/pie. Prioridad: campo `tema_detectado` del frontmatter YAML → primer H1 → `titulo` de respaldo. Se calcula **antes** del strip del frontmatter.
2. **Strip frontmatter YAML** (`---...---`).
3. **Marcadores del Agente Contenido:** `[FIGURA: ...]` → token que el parser convierte en `_FiguraPlaceholder` (rectángulo gris `#F0F0F0`, borde `#CCCCCC`, alto 60pt, "[Figura]" 9pt itálica + descripción a 2 líneas máx.); `[TEXTO_ILEGIBLE]` → blockquote italic que indica la laguna.
4. **`_protect_latex()`:** reemplaza `$$...$$` e `$...$` con tokens placeholder.
5. **Markdown → HTML** con la biblioteca `markdown` (extensiones `tables`, `fenced_code`).
6. **`_MarkdownFlowableParser`** (HTMLParser custom): jerarquía de encabezados — H1 20pt azul, **H2 14pt azul con línea separadora `#003366` 1pt y salto de página antes de cada uno excepto el primero**, H3 11.5pt negro, H4 10.5pt negrita itálica gris. Cuerpo 10.5pt interlineado 1.4, justificado, 8pt tras párrafo. Listas con bullet `•`/contador en azul, sangría 0.5cm. Tablas → `Table` ReportLab con cabecera `#003366` texto blanco 9.5pt negrita, filas pares `#F5F7FA`, borde exterior `#003366` 0.75pt, interior `#CCCCCC` 0.4pt, ancho 100% de la columna, `repeatRows` para repetir cabecera entre páginas.
7. **Ecuaciones en bloque** (`$$...$$`): `render_latex_to_image()` (matplotlib mathtext, `usetex=False`) como PNG. Escala a máx. **70%** del ancho de columna, centrada, con 14pt de espacio antes y después. Fallback a Courier en `_LeftBorderBox`.
8. **Ecuaciones inline** (`$...$`): `<img>` inline a 12pt de altura; fallback `<font name="Courier">`.
9. **Fuente base:** Arial del sistema si las cuatro variantes TTF existen (`_registrar_arial()`); si no, Helvetica (sin dependencias). Cualquier fallo al registrar TTF degrada a Helvetica sin bloquear.
10. **Cabecera (`_dibujar_cabecera`, todas las páginas):** logo UO de `assets/logo_uniovi.png` (alto 1cm, proporción preservada) a la izquierda; nombre de asignatura a la derecha (Helvetica 8pt `#003366`); línea separadora `#003366` 0.5pt al borde inferior, a 1.2cm del borde superior. Si el logo no está o falla su lectura → fallback de texto "Universidad de Oviedo | EPI Gijón". **Nunca lanza excepción por el logo.**
11. **Pie (`_numbered_canvas_factory`, todas las páginas):** patrón NumberedCanvas de dos fases (acumula estados en `showPage()`, los reemite en `save()` con el total real) → "[asignatura] | Universidad de Oviedo | Página X de N", Helvetica 8pt `#666666` centrado, línea `#CCCCCC` 0.5pt arriba. El total **N nunca es "?"**.
12. **Márgenes:** superior 2.5cm, inferior 2cm, izquierdo 2.5cm, derecho 2cm.
13. Las imágenes PNG temporales se escriben a disco y se eliminan en el bloque `finally`.

**Logo:** `assets/logo_uniovi.png` está versionado en el repo. `_cargar_logo()` lo lee con `ImageReader` y valida `getSize()`; cualquier problema → `None` → fallback de texto.

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

**Inicialización (obligatorio):**
Todo el código de inicialización de Chart.js debe estar dentro de `window['initBloque_{slug}'] = function() { ... }`, definida en el scope global del script (nunca anidada). Hay doble arranque deliberado: (1) cada bloque registra al final de su `<script>` un listener `DOMContentLoaded` que llama a `window['initBloque_{slug}']()` dentro de try/catch con `console.error` — garantiza que la primera pestaña se inicializa en carga; (2) el contenedor llama a la misma función cuando la pestaña se activa (tras MathJax), también con try/catch. Por eso la función debe ser idempotente: la destrucción previa del chart no es opcional. La llamada se hace siempre como `window['initBloque_{slug}']()` porque el slug contiene guiones y no es un identificador JS válido.

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
- **HTML interactivo + presentación completa** (identidad de marca de la suite):
  - Acento: `#185FA5` / hover: `#0C447C`
  - Fondo de página: `#F7F5F0`
  - Superficie de card: `#FFFFFF`
  - Superficie de control (sliders): `#F0EEE9`
  - Borde sutil: `rgba(0,0,0,0.08)`
  - Card del bloque interactivo en presentación: borde izquierdo `#003366`, fondo `#EEF2F7`
- **PDF** (plantilla institucional Universidad de Oviedo):
  - Acento institucional: `#003366` (encabezados, líneas separadoras, cabecera tabla, borde tabla, separador de cabecera)
  - Cuerpo de texto: `#1A1A1A`
  - Filas pares de tabla: `#F5F7FA`
  - Pie de página y descripción de figura: `#666666` / `#888888`
  - Líneas de pie e interior de tabla: `#CCCCCC`

**Tabla de variables — filas sin descripción (`construir_tabla_variables`, sección 6):**
Función compartida por el HTML por pestañas y la presentación completa. Cuando Haiku no genera la descripción de una variable (degradación graceful), esa fila se **omite** en lugar de mostrar "Descripción no disponible". Si tras filtrar no queda ninguna fila, la lista vacía hace que el generador omita la tabla por completo. Cambiar este filtro afecta a ambos outputs HTML.

---

## 10. DEPURACIÓN

**Activar verbose:**
```python
html_str = generar_html(elementos_sel, titulo, verbose=True, texto_original=texto)
```
`verbose=True` es el valor por defecto en `generar_html()`. Los logs internos usan `logging`; para verlos en Streamlit:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

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

## 11. RESILIENCIA DE LA API (generación de bloques)

El bucle de reintentos de `_generar_bloque()` (`generador_html.py`) maneja dos modos de fallo además del bloque incompleto:

- **Reintento correctivo:** si un intento es rechazado por `validar_bloque_html()`, el siguiente reenvía a Sonnet el motivo exacto del rechazo y la plantilla obligatoria de `window['initBloque_{slug}']` + arranque `DOMContentLoaded`. Repetir el mismo mensaje tendía a reproducir el mismo fallo de formato.
- **Backoff ante `RateLimitError` (429):** el límite de output tokens/min de la organización se agota al generar varios bloques en paralelo. Ante un 429 se espera 30/60 s antes del siguiente intento en vez de rechocar de inmediato. La presentación completa además limita a 2 workers.

`construir_tabla_variables()` degrada graciosamente si Haiku falla (sin crédito o sin red): las variables sin descripción se omiten de la tabla (ver sección 9).

---

## 12. PENDIENTE

Sin items pendientes en el pipeline principal. Los tres outputs (PDF institucional, HTML por pestañas, HTML presentación completa) están implementados y validados con análisis estático sobre `TEMA7_Calidad_maquinas_con_ejercicios_curado.md`.
