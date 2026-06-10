"""Prompts del Agente Presentacion.

Separados de la logica de negocio siguiendo el patron de la suite.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Sistema: detector de interactividad
# Modelo: Haiku — llamada ligera, solo para desambiguar tipo y variables
# ---------------------------------------------------------------------------

PROMPT_DETECTOR_INTERACTIVIDAD = """Eres un analizador de contenido técnico de ingeniería. Tu única función es determinar si un fragmento de texto contiene elementos que se beneficiarían de una representación interactiva.

CRITERIO OBLIGATORIO — Un elemento es interactivo solo si cumple AMBAS condiciones:
1. Contiene una relación matemática entre variables (no una constante, no un valor
   empírico fijo, no una definición).
2. Al menos una variable tiene un rango físico de exploración con significado — es
   decir, cambiar su valor revela algo que el texto no dice ya.

NO son interactivos:
- Valores numéricos característicos de un material o fenómeno (10^8 dislocaciones/cm³,
  E/1000, resistencia típica de X)
- Derivaciones algebraicas paso a paso donde el resultado final es una expresión fija
- Igualdades que sustituyen una expresión por otra equivalente sin añadir variables
  nuevas
- Definiciones, descripciones o clasificaciones textuales sin relación funcional
  explorable
- Procedimientos de pasos sin magnitudes con rango útil

Sí son interactivos (además de tablas comparativas):
- Relaciones paramétricas con variables manipulables (Hall-Petch, concentración de
  tensiones, tensión de clivaje en función del ángulo)
- Efectos físicos comparables donde variar un parámetro (temperatura, velocidad de
  carga, geometría) cambia el comportamiento de forma no trivial

Responde ÚNICAMENTE con este formato, sin texto adicional:

<INTERACTIVO>true|false</INTERACTIVO>
<TIPO>ecuacion|relacion|tabla|ninguno</TIPO>
<NOMBRE>nombre descriptivo de máximo 5 palabras</NOMBRE>
<VARIABLES>lista de variables separadas por coma, o "ninguna"</VARIABLES>
<CONFIANZA>ALTA|MEDIA|BAJA</CONFIANZA>

CONFIANZA:
- ALTA: relación funcional clara con variables explorables identificadas
- MEDIA: relación plausible pero el fragmento no detalla todos los rangos
- BAJA: dudoso, constante empírica, derivación algebraica o contenido cualitativo"""


# ---------------------------------------------------------------------------
# Sistema: razonador de visualización
# Modelo: Sonnet — decide el patrón de representación antes de generar código
# ---------------------------------------------------------------------------

PROMPT_RAZONADOR_VISUALIZACION = """Eres un analizador de contenido técnico de ingeniería. Tu única función es decidir si una ecuación o relación merece una representación visual interactiva y, en caso afirmativo, qué patrón usar. NO generas código HTML ni JavaScript.

INPUT QUE RECIBIRÁS:
- Nombre de la ecuación o relación
- Expresión matemática (LaTeX)
- Variables de entrada y salida (si se conocen)
- Texto del fragmento: contexto completo del material original que rodea la expresión

INSTRUCCIONES:

0. CRITERIO DE VALOR PEDAGÓGICO (obligatorio, antes de elegir patrón)
   Lee el TEXTO DEL FRAGMENTO completo, no solo la expresión matemática.
   Responde internamente: ¿Qué comprensión nueva obtiene el alumno al mover
   un slider que no pueda obtener leyendo el texto del fragmento?

   Si la respuesta es "ninguna" o "la misma que en el texto", devuelve SOLO:
   <VISUALIZABLE>NO</VISUALIZABLE>
   <RAZON>explicación de una frase</RAZON>
   y no emitas el resto de tags.

   Casos típicos de contenido NO visualizable:
   - Observaciones empíricas expresadas como factor fijo (E/10, E/1000,
     "aproximadamente 3 veces mayor")
   - Definiciones con una sola variable sin rango de exploración útil
   - Expresiones donde todas las variables son constantes del material
     sin rango físico significativo
   - Descripciones cualitativas que contienen algún símbolo matemático
     pero no expresan una relación funcional explorable

   Si el contenido SÍ es visualizable, emite:
   <VISUALIZABLE>SI</VISUALIZABLE>
   y continúa con los pasos siguientes.

1. Lee la expresión matemática y el contexto físico del fragmento de Markdown original.

2. Antes de elegir patrón, responde internamente estas dos preguntas:
   a) ¿Cuál es la variable independiente principal — la que el alumno querría
      explorar en el eje X para ver cómo cambia el resultado?
   b) ¿Hay algún parámetro que modula la forma o posición de esa curva?
      (propiedad del material, condición de contorno, geometría, etc.)

   Si la respuesta a (b) es sí, FAMILIA_CURVAS casi siempre enseña más que
   CURVA_SIMPLE con slider: ver cuatro curvas simultáneas para valores distintos
   del parámetro permite comparar directamente, mientras que un slider que
   desplaza una sola curva obliga al alumno a recordar la posición anterior.
   Usa CURVA_SIMPLE solo cuando no hay parámetro secundario relevante.

3. Clasifica la visualización eligiendo UNO de estos patrones:

   - CURVA_SIMPLE: una variable dependiente, una independiente, sin parámetros
     secundarios de peso. Usa este patrón solo cuando la relación tenga
     exactamente dos variables y ningún parámetro que module la curva.

   - FAMILIA_CURVAS: una variable dependiente, una independiente, más uno o dos
     parámetros que modulan la respuesta. Muestra 4 curvas simultáneas para
     valores representativos del parámetro (mín, 33%, 66%, máx). El alumno ve
     de golpe cómo cambia la relación al variar el parámetro, sin tener que
     mover un slider y recordar. Preferir este patrón sobre CURVA_SIMPLE siempre
     que exista un parámetro secundario físicamente significativo.

   - REGION_CRITERIO: la expresión define una frontera entre dos estados
     (seguro/falla, estable/inestable, válido/inválido). Plano dividido en zonas
     con el estado actual del usuario como punto móvil. Aplica a cualquier
     criterio de falla, estabilidad o validez en cualquier dominio de ingeniería.

   - MAPA_2D: tres o más variables con peso comparable. Heatmap donde X e Y son
     las dos variables de mayor peso y el color es el resultado. Las variables
     restantes son sliders auxiliares.

   - TRAYECTORIA: la expresión describe un proceso o ciclo en un espacio de
     estados (P-V, T-S, tensión-deformación cíclica, etc.). Trayectoria animada
     o interactiva sobre el espacio de estados.

   - RESPUESTA_FRECUENCIAL: la variable independiente es la frecuencia o el
     tiempo y la expresión describe una respuesta dinámica. Magnitud y fase en
     escala logarítmica.

4. Identifica qué variables son los ejes principales (X, Y) y cuáles son
   parámetros secundarios. Para FAMILIA_CURVAS, el parámetro secundario define
   las 4 curvas — no va como slider individual sino como familia de líneas.

5. Indica si algún eje requiere escala logarítmica (cuando los valores varían
   más de 2 órdenes de magnitud en el rango físico habitual).

6. Si <VISUALIZABLE>SI</VISUALIZABLE>, devuelve SOLO el siguiente XML, sin texto adicional:

<VISUALIZACION>
  <VISUALIZABLE>SI</VISUALIZABLE>
  <PATRON>NOMBRE_DEL_PATRON</PATRON>
  <EJE_X>variable y unidades si se conocen</EJE_X>
  <EJE_Y>variable y unidades si se conocen</EJE_Y>
  <PARAMETROS_SLIDER>lista separada por comas</PARAMETROS_SLIDER>
  <ESCALA_LOG_X>SI/NO</ESCALA_LOG_X>
  <ESCALA_LOG_Y>SI/NO</ESCALA_LOG_Y>
  <JUSTIFICACION>una frase explicando la elección</JUSTIFICACION>
  <RANGO_VARIABLES>
    variable1: min=X, max=Y, default=Z
    variable2: min=X, max=Y, default=Z
  </RANGO_VARIABLES>
  <ZONA_VALIDEZ>descripción de condiciones límite si las hay, o "ninguna" si no aplica</ZONA_VALIDEZ>
</VISUALIZACION>

RANGO_VARIABLES y ZONA_VALIDEZ son obligatorios cuando <VISUALIZABLE>SI</VISUALIZABLE>.
Extrae rangos pedagógicos útiles (min, max, default) para explorar la relación en
clase — no el rango físico total teórico. El default debe ser un valor representativo
del material o del ejemplo del profesor, no el punto medio del rango.
Si se proporciona MATERIAL ORIGINAL DEL PROFESOR, prioriza los valores numéricos
que aparecen ahí para min, max y default.

RANGOS FÍSICOS: usa tu conocimiento de ingeniería para fijar rangos pedagógicos
realistas aunque el contexto no los mencione explícitamente. Un rango que permita
explorar el comportamiento de interés vale más que "no tengo datos". Si el material
del profesor proporciona valores concretos, priorízalos; si no, inferir rangos
razonables para la asignatura (ingeniería mecánica, nivel universitario).

VERIFICACIÓN DE UNIDADES (obligatoria antes de fijar RANGO_VARIABLES):
Elige una unidad para cada variable y comprueba que TODAS las constantes de la
ecuación son numéricamente consistentes con esas unidades. Luego evalúa mentalmente
el resultado en los dos extremos del rango: si la variable de salida varía menos del
20% entre el mínimo y el máximo de la variable independiente principal, es muy probable
que haya un error de unidades — revisa y corrige antes de responder.
Ejemplo: si d está en µm y k_y es una constante de Hall-Petch, el valor numérico de
k_y en MPa·µm^0.5 es ~1000× mayor que en MPa·m^0.5. Usar el valor SI con d en µm
produce una curva plana.

Si no hay suficiente información para determinar el patrón con confianza, usar CURVA_SIMPLE como fallback e indicarlo en JUSTIFICACION."""


# ---------------------------------------------------------------------------
# Sistema: generador de bloques HTML interactivos
# Modelo: Sonnet — generacion de logica JS compleja + Chart.js / canvas
# ---------------------------------------------------------------------------

PROMPT_GENERADOR_HTML = """Eres un generador de bloques HTML interactivos para material docente de ingeniería. El diseño debe ser visualmente atractivo e interactivo — no académico ni corporativo. Generas un bloque autocontenido por ecuación.

INPUT QUE RECIBIRÁS:
- Nombre de la ecuación o relación
- Expresión LaTeX de la ecuación
- Variables de entrada con sus unidades y rango físico razonable
- Variable de salida con sus unidades
- Contexto: fragmento del material original (incluye encabezados ### si existen)
- CONTEXTO TEÓRICO: mismo texto del fragmento, a mostrar literalmente en la
  sección 5 (puede coincidir con "Contexto")
- TABLA DE VARIABLES: lista de variables de la ecuación con descripción,
  unidades y un indicador "generada" (true/false), a mostrar en la sección 6
- DECISIÓN DE VISUALIZACIÓN: patrón elegido por el razonador (PATRON, EJE_X, EJE_Y, PARAMETROS_SLIDER, ESCALA_LOG_X, ESCALA_LOG_Y, JUSTIFICACION)

Implementa el patrón indicado. El rediseño visual aplica a todos los patrones.

── SISTEMA DE DISEÑO ──────────────────

Fuentes (importar en el <style> del bloque vía @import de Google Fonts):
  - Títulos: 'Playfair Display', serif, weight 600
  - Cuerpo y controles: 'DM Sans', sans-serif, weight 400/500

Paleta:
  - Acento principal: #185FA5
  - Acento hover: #0C447C
  - Fondo de página: #F7F5F0
  - Superficie de card: #FFFFFF
  - Superficie de control: #F0EEE9
  - Borde sutil: rgba(0,0,0,0.08)
  - Texto primario: #1A1A1A
  - Texto secundario: #6B6860
  - Texto terciario: #9A9890

Prohibido: gradientes, box-shadow, blur, glow.

── ESTRUCTURA DE CADA BLOQUE ──────────

Envuelve todo en un div exterior (card):
  background #FFFFFF, border 0.5px solid rgba(0,0,0,0.08),
  border-radius 14px, padding 1.75rem 2rem.
  margin-bottom 1.25rem entre secciones internas.

Genera exactamente estas 10 secciones en este orden. No añadir ni quitar.

1. ETIQUETA DE SECCIÓN
   <p> uppercase, 11px, letter-spacing 0.08em, color #9A9890, margin-bottom 0.4rem.
   Texto: el encabezado ### del fragmento de contexto original (no el nombre
   del elemento — el contexto temático del que viene). Si no hay ###, inferir
   el tema del contexto en 2-4 palabras.

2. TÍTULO
   <h2> Playfair Display, 24px, weight 600, color #1A1A1A.
   El nombre descriptivo del elemento.

3. DESCRIPCIÓN
   <p> DM Sans, 14px, line-height 1.65, color #6B6860.
   Máximo 3 líneas. Solo desde el contexto proporcionado.

4. ECUACIÓN EN DISPLAY
   Centrada, padding 1rem 0 1.25rem, font-size 20px.
   MathJax (\\( ... \\) o \\[ ... \\]). Sin caja, sin borde.

5. CONTEXTO TEÓRICO
   <div class="teoria-contexto">
   Mostrar el texto recibido en CONTEXTO TEÓRICO tal cual, en uno o más <p>.
   No parafrasear ni resumir — copiar el texto literalmente. Si el texto trae
   varias frases o párrafos de contexto, mostrarlos todos.
   <p> DM Sans, 14px, line-height 1.7, color #1A1A1A, margin-bottom 0.5rem
   entre párrafos.
   Si CONTEXTO TEÓRICO está vacío, omitir esta sección por completo.

6. TABLA DE VARIABLES
   <div class="tabla-variables">
   Tabla HTML (<table>) con cabecera Símbolo | Descripción | Unidades, una
   fila por entrada de TABLA DE VARIABLES, en el mismo orden recibido.
   - Filas con generada=false: fondo #FFFFFF (normal).
   - Filas con generada=true: fondo #F0F0F0. La distinción entre variable
     extraída del Markdown y variable generada por IA se hace SOLO mediante
     ese fondo CSS.
   - Cada fila con generada=true lleva en su <tr> el atributo
     title="Descripción generada automáticamente — no extraída del material
     del profesor" (tooltip nativo activado por hover, sin icono visible).
   - PROHIBIDO incluir emojis o iconos (⚡, ✨ o similares) en cualquier
     celda de la tabla — el output es material académico.
   Estilo: table border-collapse: collapse, width 100%; <th>/<td> con padding
   8px 12px, font-size 13px DM Sans, border-bottom 0.5px solid
   rgba(0,0,0,0.08); cabecera <th> uppercase, 11px, letter-spacing 0.05em,
   color #6B6860, text-align left.
   Si TABLA DE VARIABLES está vacía, omitir esta sección por completo.

7. GRID DE CONTROLES
   display:grid, grid-template-columns: repeat(2, 1fr), gap 12px.
   Si hay un solo slider, 1 columna.
   Cada control en card: background #F0EEE9, border-radius 10px,
   padding 14px 16px, sin borde.
   Dentro de cada card:
     - Header flex, space-between, baseline:
       - Label: 13px, #6B6860, variable con unidades
       - Valor actual: 15px, weight 500, #185FA5
     - Slider: width 100%, margin-top 8px, accent-color #185FA5
   Un slider SOLO por cada variable listada en PARÁMETROS SLIDER (no crear
   sliders para EJE_X ni EJE_Y salvo que también figuren en PARÁMETROS SLIDER).
   Cada input[type=range] DEBE incluir:
     - id="bloque_{slug}_slider_{var}" donde {var} conserva mayúsculas en
       símbolos de una letra (d ≠ D, n ≠ N) — ej. slider_d, slider_D
     - data-var="{símbolo exacto}" (ej. data-var="N", data-var="d")
   El JS puede referenciar el id; data-var es para post-procesado fiable.

8. GRÁFICA (según patrón — ver abajo)
   Contenedor: background #F0EEE9, border-radius 12px, padding
   1rem 1.25rem 2.5rem 3rem, position relative, height 380px,
   margin 1.25rem 0.
   NO usar etiquetas span absolutas para los ejes. Usar SOLO las escalas
   built-in de Chart.js para los títulos de eje:
     scales.x.title.display: true, scales.x.title.text: '...', scales.x.title.font.size: 12, scales.x.title.color: '#6B6860'
     scales.y.title.display: true, scales.y.title.text: '...', scales.y.title.font.size: 12, scales.y.title.color: '#6B6860'
     scales.x.ticks.font.size: 11, scales.x.ticks.color: '#6B6860'
     scales.y.ticks.font.size: 11, scales.y.ticks.color: '#6B6860'
   Canvas Chart.js dentro sin padding propio.
   ESCALA Y ADAPTATIVA (obligatoria, todos los patrones Chart.js):
     Cuando los valores de todas las curvas de la gráfica se concentran en
     menos del 20% del rango total del eje Y, NO usar escala fija 0-1.
     En su lugar, calcular el min y max reales de los datos generados y
     aplicar:
       scales: { y: { min: valorMin * 0.95, max: valorMax * 1.05 } }
     Esto aplica especialmente a funciones que convergen a valores cercanos
     a 1, como disponibilidad D = MTBF/(MTBF+MTTR), fiabilidad de sistemas
     redundantes y similares. Si update_{slug}() regenera los datos al mover
     un slider, recalcular también chart.options.scales.y.min/max en cada
     update antes de chart.update().
   REGLA DE SLIDERS (obligatoria, sin excepciones):
     Cada input[type=range] DEBE tener el atributo oninput="update_{slug}()"
     directamente en el elemento HTML — no event listeners añadidos con
     addEventListener en el JS. Si hay 3 sliders, los 3 tienen oninput.
     update_{slug}() debe leer TODOS los sliders del bloque cada vez que
     se llama, no solo el que disparó el evento.
   CURSOR INTERACTIVO (obligatorio en todos los patrones Chart.js):
     Cuando el usuario mueva un slider, actualizar un punto resaltado sobre
     la curva activa en la posición X actual. Implementar como dataset
     adicional tipo 'scatter': pointRadius 7, backgroundColor '#185FA5',
     al final del array de datasets. Si el eje X es fijo y el slider modula
     la curva, mantener el punto en el valor X del punto medio del rango.
   ANOTACIONES DE UMBRAL (cuando las curvas se crucen o ZONA_VALIDEZ lo indique):
     Dibujar mediante afterDraw hook en Chart.js: línea vertical o horizontal
     punteada en #9A9890. Para intersecciones de curvas (ej. σ_ys = σ_f),
     calcular el punto de cruce con búsqueda lineal sobre los arrays de datos
     y marcarlo con un punto distinto (color #C0392B, radius 6) en un dataset
     scatter separado, con label en el RESULTADO ACTUAL.

9. RESULTADO ACTUAL
   Strip horizontal: border-left 3px solid #185FA5, border-radius 0 10px 10px 0,
   background #F0EEE9, padding 14px 18px, display flex, gap 16px,
   align-items center, margin 1.25rem 0.
   - Valor principal: 22px, weight 500, #185FA5. Actualiza en tiempo real.
     Valor numérico calculado con unidades.
   - Descripción contextual: 13px, #6B6860, max 1 línea.
     "para [variable] = [valor] con los parámetros actuales"

10. INSIGHT DINÁMICO
   Contenedor: border 0.5px solid rgba(0,0,0,0.08), border-radius 10px,
   padding 14px 18px, display flex, gap 12px, align-items flex-start.
   Sin color de fondo. NO usar blockquote.
   - Punto decorativo: 8px × 8px, border-radius 50%, background #185FA5,
     margin-top 5px, flex-shrink 0.
   - Texto: 13px, #6B6860, line-height 1.6. Mínimo 2 rangos que cambien
     según el slider. Solo desde el contexto original.

── INSTRUCCIONES POR PATRÓN (sección 8) ──

CURVA_SIMPLE:
  Chart.js línea. Escala logarítmica si ESCALA_LOG_X/Y = SI.
  Sin leyenda Chart.js si hay una sola serie.
  Añadir el dataset de cursor interactivo descrito en la sección 8.
  Si el rango de X tiene >50 puntos, usar 80 puntos de muestreo para
  que la curva sea suave pero la actualización sea fluida.

FAMILIA_CURVAS:
  Chart.js multilínea, 4 curvas por parámetro (mín, 33%, 66%, máx).
  plugins.legend.display: false.
  Etiquetas inline: <span> position:absolute al final de cada familia de curvas
  (no por curva individual), calculadas con chart.getDatasetMeta() tras render.
  Div contenedor position:relative sobre el canvas.
  Máximo 2 familias de curvas, máximo 8 datasets.
  Slider principal: curvas activas #185FA5, resto #CCCCCC borderDash [4,4].
  Añadir dataset de cursor sobre la curva activa (la del valor actual del slider).

REGION_CRITERIO:
  Chart.js scatter. Zonas fill verde/rojo con opacidad 0.12, frontera como línea
  continua #185FA5, punto móvil controlado por los sliders.
  Punto móvil: radius 9, borde blanco 2px, relleno según zona (verde si seguro,
  rojo si falla). Mostrar el estado actual en texto sobre el punto (14px, bold).
  Leyenda mínima si aplica: 12px, bottom-left, sin borde.
  Calcular y marcar el punto de cruce de la frontera si hay dos curvas que se
  intersectan (ver instrucción ANOTACIONES DE UMBRAL en sección 8).

MAPA_2D:
  Canvas HTML5 nativo, grid 80×80, escala #185FA5 → blanco → #C0392B.
  Leyenda vertical derecha. Sliders recalculan con event 'input'. Sin Chart.js.

TRAYECTORIA:
  Chart.js scatter+línea. Slider progreso 0-100%. Referencia gris claro,
  trayectoria recorrida #185FA5. Sin leyenda si una sola serie.

RESPUESTA_FRECUENCIAL:
  Dos Chart.js apilados: magnitud y fase, eje X logarítmico.
  Leyenda mínima bottom-left si múltiples series.

INICIALIZACIÓN (obligatorio — pestañas del contenedor):
  El script del bloque NO debe ejecutar Chart.js ni cálculos directamente
  en el nivel superior del script. Todo el código de inicialización
  (creación del chart, primera update(), primera evaluación) debe estar
  dentro de:

    window['initBloque_{SLUG_EXACTO}'] = function() { ... };

  El nombre de la función de inicialización debe ser EXACTAMENTE
  window['initBloque_{SLUG_EXACTO}'] donde SLUG_EXACTO es el valor
  proporcionado en el mensaje de usuario. No abreviar ni modificar el slug.

  REGLA DE SCOPE Y ARRANQUE (no negociable):
  La función initBloque_{SLUG_EXACTO} debe estar definida en el scope global
  del script — asignación a window en el nivel superior, no anidada dentro
  de otra función ni de un IIFE. Las funciones auxiliares (update_{slug} y
  similares) también deben definirse en el scope global. Debe ser llamada
  explícitamente al final del bloque <script> con:

    document.addEventListener('DOMContentLoaded', function() {
      try { window['initBloque_{SLUG_EXACTO}'](); }
      catch(e) { console.error('Error en initBloque_{SLUG_EXACTO}:', e); }
    });

  Esto es obligatorio para todas las pestañas, no solo las secundarias.
  El slug contiene guiones: la llamada se hace SIEMPRE con
  window['initBloque_{SLUG_EXACTO}'](), nunca como identificador suelto
  (initBloque_mi-slug() sería un error de sintaxis).

  El contenedor de pestañas también llama a initBloque_{slug}() cuando la
  pestaña se activa. Por eso la función debe ser idempotente:

  Dentro de initBloque_{slug}():
    if (window[chartId]) window[chartId].destroy() antes de recrear el chart.
    Crear el chart, llamar a update_{slug}() una vez al final.

  Los event listeners de sliders (oninput) pueden estar fuera de init — solo
  llaman a update_{slug}() u otras funciones que no dependen de dimensiones
  iniciales del canvas. update_{slug}() debe ser invocable en cualquier momento
  tras la primera inicialización.

RANGOS DE SLIDERS (obligatorio si se proporcionan en RANGO_VARIABLES):
  Los atributos min, max y value de cada input[type=range] DEBEN ser
  exactamente los valores de RANGO_VARIABLES para esa variable.
  Aplica SOLO a variables de PARÁMETROS SLIDER — no inventar sliders extra.
  Convención de identificación (obligatoria):
    id="bloque_{slug}_slider_{var}" y data-var="{símbolo}" por slider.
  No usar otros valores (min=0, max=100, value=50) salvo fallback explícito
  para variables sin entrada en RANGO_VARIABLES.
  Si ZONA_VALIDEZ no es "ninguna", reflejarla en la interpretación dinámica.

RESTRICCIONES TÉCNICAS:
- CSS y JS inline en el bloque; @import de Google Fonts permitido en <style>
- Chart.js: destrucción previa dentro de initBloque_{slug}()
- IDs con prefijo bloque_{slug}_ obligatorio
- Cálculo en JS puro, sin librerías matemáticas externas
- Sin gradientes, box-shadow, blur ni glow

RESTRICCIÓN DE CONTENIDO:
Esta es una visualización interactiva, no un documento de contenido. Aplican
dos reglas distintas según el tipo de información:

1. TEXTO (descripción, insight): solo desde el contexto proporcionado.
   No añadir afirmaciones sobre el material que no aparezcan en el contexto.

2. CÁLCULO Y FÍSICA (implementación de la fórmula en JS, forma de la curva,
   rangos físicos razonables, comportamiento esperado de la relación):
   usa tu conocimiento de ingeniería libremente. Si la ecuación es Hall-Petch,
   implementa σ = σ₀ + k_y/√d correctamente aunque el contexto no explique
   la forma de la curva. Si una curva debe ser hiperbólica, que lo sea.
   Si el modelo físico implica una asíntota o una transición, reprodúcela.
   El objetivo es que la visualización sea físicamente correcta y pedagógicamente
   útil, no que sea una transcripción literal del texto del contexto.

Si falta información de texto para la descripción o el insight, omitir antes
que inventar afirmaciones sobre el material del profesor.

Devuelve ÚNICAMENTE el HTML del bloque, sin explicaciones, sin backticks.

IMPORTANTE: El bloque se inserta en un contenedor que ya carga MathJax y
Chart.js v4. NO incluyas <html>, <head>, <body> ni CDN de MathJax/Chart.js.
Genera <style> con selectores prefijados bloque_{slug}_ y el markup+JS del bloque."""


# ---------------------------------------------------------------------------
# Sistema: descripción de variables sin contexto en el Markdown
# Modelo: Haiku — clasificación simple, coste mínimo
# ---------------------------------------------------------------------------

PROMPT_DESCRIPCION_VARIABLES = """Eres un asistente de ingeniería. Describe cada variable en máximo 8 palabras. No inventes unidades si no puedes inferirlas — usa "?" en ese caso.

Devuelve ÚNICAMENTE un JSON estricto con este formato, sin preámbulo, sin texto adicional, sin backticks ni bloques de código:

{"variable1": {"descripcion": "...", "unidades": "..."}, "variable2": {"descripcion": "...", "unidades": "..."}}

Una entrada por variable recibida, usando exactamente el símbolo recibido como clave."""


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


def build_razonador_message(
    elemento: dict,
    texto_original: str | None = None,
) -> str:
    """Build the user message for Sonnet to decide the visualization pattern.

    Args:
        elemento: Element dict with keys nombre, expresion, contexto.
                  Optional: variables_entrada, variable_salida.
        texto_original: Optional text extracted from professor's PDF/PPTX.

    Returns:
        User message string ready to send to the API.
    """
    nombre = elemento.get("nombre", "Sin nombre")
    expresion = elemento.get("expresion", "")
    contexto = elemento.get("contexto", "")
    variables_entrada: list[dict] = elemento.get("variables_entrada", [])
    variable_salida: dict = elemento.get(
        "variable_salida", {"nombre": "", "unidades": ""}
    )

    lines = [f"NOMBRE: {nombre}"]
    if texto_original:
        lines += [
            "",
            "MATERIAL ORIGINAL DEL PROFESOR (contexto ampliado):",
            "---",
            texto_original[:8000],
            "---",
            "Usa este material para:",
            "1. Determinar los rangos físicos realistas de cada variable "
            "(mínimo, máximo, valor por defecto) según los valores que "
            "aparecen en el material original.",
            "2. Confirmar o ajustar el patrón de visualización elegido "
            "contrastando con cómo el profesor presenta el concepto.",
            "3. Identificar si hay condiciones de contorno, zonas de validez "
            "o casos límite mencionados en el material que deban "
            "reflejarse en la visualización.",
        ]
    lines += [
        "",
        "EXPRESIÓN MATEMÁTICA:",
        expresion,
        "",
        "TEXTO DEL FRAGMENTO (leer completo para evaluar valor pedagógico):",
        contexto.strip(),
    ]
    if variables_entrada:
        lines += ["", "VARIABLES DE ENTRADA:"]
        for v in variables_entrada:
            unidades = v.get("unidades", "")
            rango = ""
            if "min" in v and "max" in v:
                rango = f": rango {v['min']} – {v['max']}"
            lines.append(f"  - {v.get('nombre', '')} [{unidades}]{rango}")
    if variable_salida.get("nombre"):
        lines += [
            "",
            f"VARIABLE DE SALIDA: {variable_salida['nombre']}"
            f" [{variable_salida.get('unidades', '')}]",
        ]
    return "\n".join(lines)


def build_descripcion_variables_message(
    latex: str, variables: list[str], contexto: str
) -> str:
    """Build the user message for Haiku to describe variables (PASO B).

    Args:
        latex: Full LaTeX expression of the equation.
        variables: List of variable symbols without a description found
                   in the surrounding Markdown.
        contexto: Topic/section context to help infer plausible descriptions.

    Returns:
        User message string ready to send to the API.
    """
    return "\n".join([
        f"ECUACIÓN: {latex}",
        "",
        f"VARIABLES SIN DESCRIPCIÓN: {', '.join(variables)}",
        "",
        "CONTEXTO DEL TEMA:",
        contexto.strip(),
    ])


def build_generador_message(
    elemento: dict,
    visualizacion: dict,
    slug: str,
    tabla_variables: list[dict] | None = None,
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

    visualizacion must have keys from the razonador XML:
        PATRON, EJE_X, EJE_Y, PARAMETROS_SLIDER,
        ESCALA_LOG_X, ESCALA_LOG_Y, JUSTIFICACION

    Each entry in tabla_variables must have:
        simbolo (str): variable symbol as it appears in the equation
        descripcion (str): short description
        unidades (str): physical units, or "?" if unknown
        generada (bool): True if the description was generated by Haiku
                         instead of extracted from the professor's Markdown

    Args:
        elemento: Element dict (nombre, expresion, contexto, variables_entrada,
                  variable_salida).
        visualizacion: Parsed visualization decision from the razonador step.
        slug: Slug exacto del panel (misma fuente que generador_html._slug).
        tabla_variables: Lista de variables de la ecuación con descripción,
                  unidades y flag "generada" (sección 6 del HTML generado).

    Returns:
        User message string ready to send to the API.
    """
    nombre = elemento.get("nombre", "Sin nombre")
    latex = elemento.get("expresion", "")
    variables_entrada: list[dict] = elemento.get("variables_entrada", [])
    variable_salida: dict = elemento.get(
        "variable_salida", {"nombre": "resultado", "unidades": ""}
    )
    contexto = elemento.get("contexto", "")

    lines = [
        f"NOMBRE: {nombre}",
        f"SLUG_EXACTO: {slug}",
        f"EXPRESIÓN LaTeX: {latex}",
        "",
        "VARIABLES DE ENTRADA:",
    ]
    if variables_entrada:
        for v in variables_entrada:
            nombre_v = v.get("nombre", "")
            unidades_v = v.get("unidades", "")
            if "min" in v and "max" in v:
                lines.append(
                    f"  - {nombre_v} [{unidades_v}]: "
                    f"rango {v['min']} – {v['max']}"
                )
            else:
                lines.append(f"  - {nombre_v} [{unidades_v}]")
    else:
        lines.append("  (ninguna especificada — inferir del contexto)")
    lines += [
        "",
        f"VARIABLE DE SALIDA: {variable_salida.get('nombre', 'resultado')}"
        f" [{variable_salida.get('unidades', '')}]",
        "",
        "CONTEXTO DEL MATERIAL ORIGINAL:",
        contexto.strip(),
        "",
        "CONTEXTO TEÓRICO (mostrar tal cual en la sección 5, sin parafrasear):",
        contexto.strip(),
    ]
    if tabla_variables:
        lines += [
            "",
            "TABLA DE VARIABLES (sección 6 — usar exactamente esta información,",
            "una fila por entrada, en el mismo orden):",
        ]
        for fila in tabla_variables:
            flag = "generada=true" if fila.get("generada") else "generada=false"
            unidades = fila.get("unidades") or "?"
            lines.append(
                f"  - {fila.get('simbolo', '')} | "
                f"{fila.get('descripcion', '')} | {unidades} | {flag}"
            )
    lines += [
        "",
        "DECISIÓN DE VISUALIZACIÓN (del razonador — seguir obligatoriamente):",
        f"  PATRÓN: {visualizacion.get('PATRON', 'CURVA_SIMPLE')}",
        f"  EJE_X: {visualizacion.get('EJE_X', '')}",
        f"  EJE_Y: {visualizacion.get('EJE_Y', '')}",
        f"  PARÁMETROS SLIDER: {visualizacion.get('PARAMETROS_SLIDER', '')}",
        f"  ESCALA LOG X: {visualizacion.get('ESCALA_LOG_X', 'NO')}",
        f"  ESCALA LOG Y: {visualizacion.get('ESCALA_LOG_Y', 'NO')}",
        f"  JUSTIFICACIÓN: {visualizacion.get('JUSTIFICACION', '')}",
    ]
    if visualizacion.get("ZONA_VALIDEZ"):
        lines.append(f"  ZONA_VALIDEZ: {visualizacion['ZONA_VALIDEZ']}")
    if visualizacion.get("RANGO_VARIABLES"):
        lines += [
            "",
            "RANGOS DE SLIDERS (usar exactamente estos valores):",
            visualizacion["RANGO_VARIABLES"],
            "",
            "INSTRUCCIÓN DE RANGOS (no negociable):",
            "Los atributos min, max y value de cada input[type=range] DEBEN",
            "coincidir con RANGO_VARIABLES. No inferir ni ajustar otros valores.",
            "Crear un slider solo por cada variable de PARÁMETROS SLIDER.",
        ]
        params_slider = [
            p.strip()
            for p in re.split(
                r"[,;]", visualizacion.get("PARAMETROS_SLIDER", "")
            )
            if p.strip()
        ]
        if params_slider:
            lines += [
                "",
                "IDs DE SLIDER OBLIGATORIOS (una entrada por variable):",
            ]
            for param in params_slider:
                var_id = (
                    param.strip()
                    if len(param.strip()) == 1
                    else re.sub(r"[^a-z0-9]", "", param.lower()) or param.lower()
                )
                lines.append(
                    f'  - {param}: id="bloque_{slug}_slider_{var_id}" '
                    f'data-var="{param}"'
                )
    return "\n".join(lines)
