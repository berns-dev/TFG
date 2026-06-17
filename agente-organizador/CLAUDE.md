# Agente Organizador — Estado del proyecto

**Monorepo:** `berns-dev/TFG`
**Última actualización:** 2026-06-17

---

## Propósito

Extrae temas, subbloques y distribución horaria de una asignatura a partir de la guía docente y los materiales de teoría. Produce un Markdown con la distribución temática y las horas asignadas por subbloque.

**Principio rector:** Extrae y estructura. No inventa. Si algo no está en el material del profesor, no aparece en el output. Cada subbloque propuesto debe poder justificarse señalando una referencia concreta del documento fuente.

---

## Estado

**Funcional. Validado con tres asignaturas reales:**
- Oleohidráulica y Neumática
- Elementos de Máquinas
- Tecnología de Materiales

---

## Stack técnico

- **UI:** Streamlit (`layout="wide"`, sidebar para uploads)
- **API:** Anthropic directo — `claude-sonnet-4-5` (generación y refinamiento)
- **Extracción:** `pdfplumber` (PDF), `python-pptx` (PPTX) vía `parser.py`
- **Credenciales:** `.env` + `python-dotenv`

---

## Arquitectura de archivos

```
app.py        — UI Streamlit + lógica de sesión + validación + edición manual
agente.py     — cliente Anthropic, ejecutar_agente()
parser.py     — TODA la lógica pura importable (ver abajo): extracción de texto,
                señales estructurales, horas, normalización, parseo/serialización
prompts.py    — construir_prompt(), construir_prompt_refinamiento()
```

### Separación lógica pura ↔ interfaz (fuente de verdad importable)

`parser.py` es el **único módulo importable** con toda la lógica de cálculo y
transformación del Organizador. No depende de Streamlit, así que cualquier otra
interfaz (en particular `app-unificada/app.py`) puede importarlo sin arrastrar
`st.set_page_config()` ni estado de sesión. `app.py` (standalone) es solo UI:
importa estas funciones en lugar de definirlas inline.

Funciones puras que viven en `parser.py` (antes estaban definidas dentro de
`app.py`, mezcladas con el módulo que ejecuta Streamlit al importarse):

| Función | Entrada → salida |
|---------|------------------|
| `extraer_horas_docencia(texto_guia)` | texto guía → `{horas_teoria, horas_aula, horas_laboratorio}` |
| `normalizar_horas_output(md, total)` | Markdown + horas objetivo → `(md_corregido, info_ajuste\|None)` |
| `contar_bloques_output(md)` | Markdown → nº de `## Bloque N` |
| `construir_nombre_descarga(texto_guia)` | texto guía → nombre de fichero |
| `parsear_bloques_desde_markdown(md)` | Markdown → bloques simples `{numero,nombre,horas,subtemas:[{nombre,horas,manual}]}` (para edición manual) |
| `parsear_bloques_organizador(md)` | Markdown → bloques enriquecidos `{…, subtemas:[{nombre,horas,orden,evidencia,origen,es_fallback}]}` (para persistir en BD) |
| `regenerar_markdown_desde_bloques(bloques, md)` | estado estructurado → Markdown (preserva cabecera/pie) |

**Consumo desde `app-unificada`:** la app unificada carga `parser.py` vía
`importlib` como `_org_parser` y llama `_org_parser.<funcion>`. Ya **no** existen
copias literales de estas funciones en `app-unificada/app.py` (se eliminaron al
hacerlas importables).

---

## Flujo principal

1. **Extracción** — `extraer_texto()` sobre guía docente y materiales de teoría
2. **Clasificación** — `clasificar_archivo()` separa "teoría" de "contexto/outline"
3. **Detección de señales estructurales** — `extraer_candidatos_con_evidencia()` en `parser.py`:
   - Prioridad 1: secciones numeradas en el texto (`3.2. Título`) → evidencia = "Sección 3.2"
   - Prioridad 2 (solo PPTX): títulos de diapositiva → evidencia = "Slide N"
   - Fallback: si ninguna fuente ofrece señal verificable, retorna `[]`; el bloque se trata como un único subbloque
4. **Editor de subbloques** — interfaz de revisión (fase `"editar"`): el profesor ve las señales detectadas con su evidencia, edita la lista en un textarea, y confirma
5. **Detección de horas** — `extraer_horas_docencia()` en `parser.py`
6. **Generación** — `construir_prompt()` → `ejecutar_agente()` → Sonnet
7. **Validación de cardinalidad** — `contar_bloques_output()` compara `## Bloque N` con `len(textos_teoria)`
8. **Refinamiento** — loop hasta 5 iteraciones; `construir_prompt_refinamiento()` (camino rápido)

---

## Subbloques con evidencia estructural (Objetivo 1)

### Prioridad de fuentes (estricta, no negociable)

1. **Guía docente** — `extraer_subtemas_guia()` toma los subtemas de la sección `Contenidos` de la guía, excluyendo el boilerplate administrativo (ver filtro de calidad). Si el material no aporta señal propia, se usa esta enumeración.
2. **Materiales de teoría — secciones numeradas** — encabezados con patrón `\d+(\.\d+)*\. Título` en el texto extraído. Evidencia: `"Sección X.X"`.
3. **Materiales de teoría — títulos de diapositiva PPTX** — placeholder `idx=0` o primera shape corta (<100 chars, sin saltos). Evidencia: `"Slide N"`. Solo se usa si no hay secciones numeradas.
4. **Fallback obligatorio** — si ninguna fuente ofrece señal suficientemente verificable, el bloque no se subdivide. Se crea un único subbloque igual al bloque completo y se marca `Evidencia = "Sin señal verificable"`. La interfaz muestra un aviso visible al profesor.

### Restricción de generación automática

El modelo nunca debe agrupar contenido por similitud temática libre. Cada subbloque propuesto debe justificarse señalando una evidencia concreta. Esto se aplica tanto en la generación inicial (vía `instruccion_subtemas` en `prompts.py`) como en los refinamientos.

### Flujo de evidencia

```
extraer_candidatos_con_evidencia()
  → [{nombre, evidencia, fuente}]  ← parser.py
  → editor_data[i]["candidatos_con_evidencia"]  ← app.py
  → mostrado en interfaz como referencia (read-only)
  → al confirmar: subtemas_confirmados[i] = [{nombre, origen, evidencia}]
  → construir_prompt(): "SUBTEMAS CONFIRMADOS: - nombre [Evidencia: X] [origen]"
  → LLM: columna Evidencia en la tabla de subbloques
  → output Markdown: | Subtema | Horas | Evidencia | Origen |
```

---

## Edición de la organización (Objetivo 2)

**App unificada — vista única interactiva (junio 2026):** la sección Organizador de
`app-unificada` muestra una sola superficie de edición tras generar la propuesta: por
cada bloque, nombre y horas totales editables; debajo, tabla de subbloques con columnas
Subtema / Evidencia / Origen, más acciones por fila (aprobar ✓, editar nombre, eliminar).
Añadir subbloque o bloque nuevo integrado en la misma vista. El Markdown raw queda en un
expander secundario; la vista principal es la tabla interactiva. El cuadro de
redistribución total por prompt se mantiene aparte para cambios grandes.

**Standalone:** conserva el editor manual en expander (misma lógica pura de `parser.py`).

**Horas solo a nivel de bloque (junio 2026):** se eliminó la columna Horas por subtema
del formato de salida, del prompt, del parser y de la UI. Motivo: con el material
disponible el reparto horario por subtema producía muchos valores en 0 y no era fiable;
las horas viven únicamente en el encabezado `## Bloque N — Nombre · Xh`.
`normalizar_horas_output()` redistribuye solo entre bloques.

### Controles disponibles (solo en fase de revisión)

- **Editar bloque** — nombre y horas totales del bloque (app unificada).
- **Añadir / eliminar subbloque** — nombre; evidencia/origen solo lectura salvo manual.
- **Aprobar subbloque** — marca ✓ (app unificada).
- **Añadir / eliminar bloque** — con horas a nivel de bloque.

La edición manual NO requiere verificación de señal estructural para filas añadidas a
mano — refleja el criterio pedagógico del profesor.

### Coexistencia con refinamiento por prompt

Ambos mecanismos operan sobre el mismo estado:
- Edición manual → actualiza `organizacion_bloques` → regenera `ultimo_output` con `regenerar_markdown_desde_bloques()`
- Refinamiento por IA → recibe `ultimo_output` (post-edición si la hubo) → LLM genera nueva versión → `_validar_y_persistir()` → re-parsea a `organizacion_bloques`

Los dos mecanismos coexisten sin pisarse. El estado es siempre consistente.

---

## Fases de la aplicación

| Fase | Valor | Descripción |
|------|-------|-------------|
| Inicial | `None` | Sin archivos procesados |
| Edición de subbloques | `"editar"` | Después de `extraer_y_detectar()`. Muestra editor de subbloques con señales detectadas. No hay output aún. |
| Resultado | `"resultado"` | Después de `_validar_y_persistir()`. Muestra output + editor manual + refinamiento por IA + botón "Cerrar". |
| Cerrado | `"cerrado"` | Después de "Dar organización por cerrada". Output congelado. Sin edición. Solo descarga. |

**Restricción temporal de edición:** la edición (manual y por prompt) solo está disponible en fase `"resultado"`. En fase `"cerrado"` se muestran aviso informativo, output y descarga; los controles de edición no se renderizan.

### Equivalencia con `app-unificada`

La app unificada no usa la variable `fase`; modela el mismo ciclo de vida con
`org_confirmada` (booleano) y la persistencia en BD:

| Concepto | Standalone (`app.py`) | Unificada (`app-unificada/app.py`) |
|----------|-----------------------|-------------------------------------|
| Fase de revisión | `fase == "resultado"` | `org_ultimo_output` presente y `org_confirmada == False` |
| Estructura congelada | `fase == "cerrado"` (botón "Dar por cerrada") | `org_confirmada == True` (botón "Confirmar como definitiva", que además escribe `temas`/`subtemas` en BD para el Agente Contenido) |
| Edición + refinamiento | solo en `"resultado"` | vista unificada interactiva + prompt; solo si `not org_confirmada` |
| Persistencia de cada edición manual | actualiza `ultimo_output` en sesión | actualiza `org_ultimo_output` **y** reescribe `data/{slug}/outputs/organizador/vN.md` |

### Loop de refinamiento por IA — equivalencia funcional (Objetivo verificado)

El comportamiento funcional del refinamiento es **idéntico** en ambas interfaces:
mismo prompt (`construir_prompt_refinamiento`), misma normalización de horas, tope
de **5 iteraciones**, mismo aviso al alcanzar el límite, y el camino rápido que no
re-extrae documentos. La **única diferencia es intencional** y deriva del contexto
de cada app: el standalone mantiene el estado solo en `session_state`, mientras que
la unificada además versiona cada iteración en disco (`vN.md`) y en BD
(`organizador_outputs`, con `feedback_texto` y registro de `ejecucion`). No se
unifica esta gestión de estado porque las dos arquitecturas (sesión pura vs. BD)
son legítimas para cada interfaz.

---

## Decisiones de implementación clave

### Selección de modelo
Sonnet para toda la generación y refinamiento. El razonamiento curricular requiere coherencia semántica que Haiku no garantiza con prompts de cardinalidad estricta.

### Código determinista para horas
`extraer_horas_docencia()` (en `parser.py`) resuelve la extracción de TE/PA/PL con código Python puro, sin LLM. Dos estrategias:
1. **Estrategia 1 (preferente):** detecta tabla(s) MODALIDADES por cabecera y lee la columna Horas. Elige la ventana con mayor completitud y mayor confianza en la fila PA.
2. **Estrategia 2 (fallback):** búsqueda en texto libre, exige señales horarias explícitas para evitar confundir "sesiones" con horas.

### Código determinista para señales estructurales
`extraer_candidatos_con_evidencia()` en `parser.py`. Prioridad estricta de fuentes (no negociable). No llama al LLM. Si retorna `[]`, el bloque es un único subbloque — el modelo nunca infiere subbloques libres para bloques sin señal.

### Filtro de calidad de subtemas (anti-boilerplate / anti-prosa)
`es_subtema_valido()` en `parser.py` es el guardián común aplicado en todos los caminos de detección de subtemas: descarta secciones administrativas estándar de las guías UniOvi, fragmentos de prosa (conector discursivo inicial), filas de datos numéricos y fragmentos truncados. Para la **guía docente** se usa `extraer_subtemas_guia()`, que además acota la extracción a la sección `Contenidos`. Regla de diseño: un subtema candidato debe ser un encabezado real anclado a señal estructural — nunca boilerplate ni texto corrido. Ver "Bug documentado y corregido: calidad de subtemas".

### Parseo/serialización para edición manual
- `parsear_bloques_desde_markdown(markdown)` → `[{numero, nombre, horas, subtemas}]` (forma simple para la edición manual; `manual=False` al parsear)
- `parsear_bloques_organizador(markdown)` → forma enriquecida con `orden/evidencia/origen/es_fallback`; la usa `app-unificada` al confirmar para persistir en BD
- `regenerar_markdown_desde_bloques(bloques, markdown_original)` → Markdown preservando cabecera y pie del original
- Formato serializado: `| Subtema | Horas | Origen |` (3 columnas, Origen = "Manual"/"Detectado")

Las dos funciones de parseo conviven en `parser.py` porque sirven a consumidores
distintos (edición manual vs. persistencia en BD) y devuelven formas de dato
distintas; la lógica de detección de cabeceras/filas es compartida en el módulo.

### Restricción de cardinalidad en el prompt (`prompts.py`)
`instruccion_cardinalidad` tiene tres refuerzos desde la corrección del bug (28/05/2026):
1. **Autoridad estructural:** la guía docente define la estructura (qué es un bloque, cuántos existen); los materiales de teoría son fuente de contenido, no de estructura.
2. **Regla anti-fragmentación:** un subtópico con horas propias en la guía docente sigue siendo subtema dentro de su bloque — nunca bloque independiente.
3. **Autoverificación obligatoria:** el modelo debe contar sus propios encabezados `## Bloque N` antes de responder; si el recuento difiere de `n_bloques`, debe reorganizar.

### Loop de refinamiento optimizado (`prompts.py`)
`construir_prompt_refinamiento()` es un prompt ligero que:
- Toma el output previo como base (ya tiene la estructura correcta)
- Solo aplica el último ajuste de feedback
- No re-extrae documentos ni re-detecta horas
- Mantiene la restricción de suma de horas totales si `horas_totales` está disponible
- Instruye al modelo a preservar las columnas Evidencia y Origen tal como están

---

## Bug documentado y corregido: cardinalidad de bloques

**Bug (detectado 26/05/2026):** el agente generaba N+1 bloques cuando la guía docente listaba una subsección con horas propias.

**Fix (28/05/2026):** `instruccion_cardinalidad` reescrita con tres refuerzos; `contar_bloques_output()` + `_validar_y_persistir()` añadidos; `st.warning` visible.

---

## Bug documentado y corregido: calidad de subtemas (boilerplate y fragmentos)

**Bug (detectado 17/06/2026, probando Elementos de Máquinas en `app-unificada`):** la
propuesta de subtemas incluía dos clases de basura.

1. **Boilerplate administrativo de la guía como subtema.** Bloques sin numeración en su
   material caían al fallback de la guía, y la guía aportaba sus secciones administrativas
   ("Identificación de la asignatura", "Contextualización", "Requisitos", "Competencias…",
   "Metodología…", "Evaluación…", "Recursos, bibliografía…").
2. **Fragmento de prosa del material como subtema.** Una línea de un ejemplo resuelto
   (`5.6. Además, de acuerdo a la tabla, la relación d/R es de 111. Con ello…`) matcheaba el
   regex de numeración y se aceptaba como subtema.

**Causa raíz (confirmada con los PDF reales, no la hipótesis inicial):** vivía en la capa
compartida `parser.py`, no en `app-unificada`. Las guías UniOvi **numeran sus 8 secciones de
primer nivel** y solo `5. Contenidos` contiene temario real; `extraer_subtemas_candidatos()`
cogía toda línea numerada sin distinguir cabecera administrativa, fila de tabla de horas o
prosa. No existía ningún filtro de boilerplate. El problema **no era específico de Elementos
de Máquinas**: la guía de Oleohidráulica producía 7/12 candidatos boilerplate y la de
Tecnología de Materiales 10/46 — contaminación latente en asignaturas ya "validadas" que no se
había notado porque sus materiales tenían numeración limpia o se editó el textarea a mano.

**Fix (17/06/2026), todo en `parser.py` (fuente de verdad de ambas interfaces):**

- **`es_subtema_valido(nombre)`** — filtro de calidad común aplicado en
  `extraer_subtemas_candidatos()` y en `extraer_candidatos_con_evidencia()` (numeración y
  títulos de slide). Reglas de exclusión:
  1. **Boilerplate administrativo UniOvi** — patrones estables (`_GUIA_SECCIONES_ADMIN_*`):
     identificación, contextualización, requisitos, competencias, metodología, evaluación,
     recursos/bibliografía y las filas de metodología (presenciales, clases expositivas,
     prácticas, tutorías…). **Nunca son subtema candidato, en ninguna asignatura.**
  2. **Fragmento de prosa** — empieza por conector discursivo (`_CONECTORES_PROSA`: además,
     asimismo, por tanto, es decir, con ello, por último…).
  3. **Ruido numérico** — 3+ tokens con dígitos (filas de tablas de horas / fragmentos de
     cálculo).
  4. **Fragmento truncado** — línea corta que acaba en palabra-función (`de`, `la`, `y`…),
     típica de columnas de tabla partidas.
- **`extraer_subtemas_guia(texto)`** — acota la extracción a la sección `Contenidos` de la
  guía: localiza la cabecera `N. Contenidos` y recoge subtemas numerados hasta la siguiente
  cabecera administrativa. Elimina de raíz boilerplate, tablas de horas y prosa de
  metodología/evaluación. Si no hay sección `Contenidos` (guía con otro formato), degrada a
  `extraer_subtemas_candidatos()` ya filtrada. **Ambas apps** (standalone y `app-unificada`)
  usan esta función para los candidatos de guía.

**Comportamiento ante material sin señal fiable:** los fragmentos arbitrarios se descartan, así
que el material queda sin candidatos y se aplica el fallback existente (candidatos de la guía;
si tampoco hay, bloque sin subdivisión marcado). Nunca se aceptan fragmentos de texto corrido.

**Verificación (PDF reales):** Elementos/Tec. Materiales → 12 temas limpios; Oleohidráulica →
4 temas limpios (antes 7/12 eran boilerplate); Tornillos → el fragmento `d/R` se descarta.

**Nota de sesión de prueba (no es bug):** en la sesión donde se detectó el problema se
mezclaron archivos de Elementos de Máquinas y Tecnología de Materiales porque no se cambió
la asignatura en la app antes de subir la guía. Eso explica que apareciera temario de
fractura/fatiga/corrosión al probar con PDFs de tornillos o resortes; no era un fallo del
agente ni de los ficheros en disco.

---

## Bug documentado y corregido: truncamiento de bloques al final del output

**Bug (detectado junio 2026):** en asignaturas con muchos bloques/subbloques, el último
bloque podía quedar cortado a mitad de una fila de la tabla (nombre incompleto, sin
evidencia ni origen). Patrón equivalente al fix del Agente Presentación (HTML truncado por
`max_tokens`).

**Causa raíz:** `ejecutar_agente()` usaba `max_tokens=4096`, insuficiente para
organizaciones largas; `stop_reason` no se comprobaba y no había validación posterior.

**Fix (junio 2026):**
- `max_tokens` subido a **8192** (criterio alineado con `_MAX_TOKENS_HTML` del Agente
  Presentación).
- `ejecutar_agente()` devuelve `(texto, stop_reason)`.
- `detectar_output_truncado()` en `parser.py` señala `stop_reason == max_tokens` y filas
  de tabla con celdas vacías al final; la app unificada muestra `st.error` visible.

**Nota:** el caso observado con guía mal asociada pudo inflar el volumen; conviene validar
con material limpio, pero el límite bajo y la ausencia de verificación eran reales.

---

## Output format

Fuente de verdad: plantilla en `prompts.py` → `construir_prompt()`.

**Con subbloques confirmados (flujo normal):**
```markdown
# DISTRIBUCIÓN TEMÁTICA — {NOMBRE_ASIGNATURA}

**Horas lectivas disponibles:** {TOTAL}h ({TE}h TE + {PA}h PA) | **Prácticas de laboratorio:** {PL}h *(informativo)*

---

## Bloque {N} — {NOMBRE_BLOQUE} · {HORAS_BLOQUE}h

| Subtema | Evidencia | Origen |
|---------|-----------|--------|
| {subtema} | {Sección X.X / Slide N / Sin señal verificable} | {Detectado / Manual / Fallback} |

*(repetir por bloque)*

---

> 🔬 Prácticas de laboratorio: {PL}h (sesiones prácticas, no incluidas en la distribución temática)
```

**Sin subbloques confirmados (libre):**
La columna "Evidencia" contiene la referencia estructural detectada por el LLM (más susceptible a imprecisión; el flujo normal con confirmación es preferible).

**Contrato con el Agente Contenido:** El Agente Contenido parsea bloques con `## Bloque N — … · Xh` (`parse_organization_md()` en `agente-contenido/app.py`). El cambio de columnas en la tabla de subbloques NO rompe este contrato (el Agente Contenido no parsea las filas de la tabla).

---

## Interfaz (estado actual)

### Layout `layout="wide"`
- **Sidebar:** branding + steps 1-2-3 + file uploaders + botón "Generar organización"
- **Área principal:** hero + expanders de validación + editor de subbloques (fase "editar") + resultado con editor manual (fase "resultado") o vista congelada (fase "cerrado")

### Identidad visual compartida
- **Tipografía:** Playfair Display + DM Sans
- **Acento:** `#185FA5`
- **Fondos/textos:** variables CSS de Streamlit

---

## Configuración del modelo

```
MODEL: claude-sonnet-4-5
# Haiku descartado para generación: el razonamiento de cardinalidad y la
# distribución horaria requieren consistencia semántica. Sonnet es obligatorio.
```
